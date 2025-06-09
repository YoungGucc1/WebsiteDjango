
import uuid
import os
from decimal import Decimal

from django.db import models
from django.db.models import F, Sum
from django.utils.text import slugify
from django.utils import timezone
from django.contrib.auth.models import User
from PIL import Image as PILImage

# --- Helper Function for Unique Slugs ---
def generate_unique_slug(instance, source_field='name', slug_field='slug'):
    """
    Generates a unique slug for the instance.
    Appends '-<number>' if the initial slug already exists.
    """
    if getattr(instance, slug_field) and not instance._state.adding:
        return getattr(instance, slug_field)

    base_slug = slugify(getattr(instance, source_field))
    if not base_slug:
        base_slug = str(instance.id)[:8]

    slug = base_slug
    num = 1
    ModelClass = instance.__class__
    qs = ModelClass.objects.filter(**{slug_field: slug})
    if instance.pk:
        qs = qs.exclude(pk=instance.pk)

    while qs.exists():
        slug = f"{base_slug}-{num}"
        num += 1
        qs = ModelClass.objects.filter(**{slug_field: slug})
        if instance.pk:
            qs = qs.exclude(pk=instance.pk)
    return slug


# --- Abstract Base Models ---
class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

class SeoModel(models.Model):
    """ An abstract model for common SEO fields """
    meta_title = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Optimal title for SEO (leave blank to use the object's name)."
    )
    meta_description = models.CharField(
        max_length=300, blank=True, null=True,
        help_text="Brief description for search engine listings."
    )
    meta_keywords = models.CharField(
        max_length=255, blank=True, null=True,
        help_text="Comma-separated keywords for meta tags."
    )

    class Meta:
        abstract = True


# --- Core Entity Models ---

class Image(BaseModel):
    # This model remains largely the same, it's a solid implementation.
    class ImageType(models.TextChoices):
        CATEGORY = 'category', 'Category Photo'
        PRODUCT = 'product', 'Product Photo'
        VARIANT = 'variant', 'Product Variant Photo' # Added for variants
        AUDIT = 'audit', 'Audit Photo'

    name = models.CharField(max_length=255, db_index=True, blank=True, null=True)
    file_path = models.ImageField(upload_to='images/')
    alt_text = models.CharField(max_length=255, help_text="Text description for accessibility and SEO")
    type = models.CharField(max_length=20, choices=ImageType.choices, default=ImageType.PRODUCT, db_index=True)

    def save(self, *args, **kwargs):
        # Image processing logic is great, keeping it.
        super().save(*args, **kwargs)
        if self.file_path:
            try:
                img_path = self.file_path.path
                with PILImage.open(img_path) as img:
                    max_size = (1920, 1080)
                    img.thumbnail(max_size, PILImage.Resampling.LANCZOS)
                    # Convert to RGB to ensure compatibility with JPEG
                    final_img = img.convert('RGB') if img.mode not in ('RGB', 'L') else img
                    final_img.save(img_path, format='JPEG', quality=85, optimize=True)
            except (FileNotFoundError, IOError) as e:
                print(f"Warning: Could not process image {getattr(self.file_path, 'path', 'N/A')}: {e}")

    def __str__(self):
        return self.alt_text or os.path.basename(self.file_path.name)

class Category(BaseModel, SeoModel):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children')
    image = models.ForeignKey(Image, null=True, blank=True, on_delete=models.SET_NULL, related_name='categories')

    class Meta(BaseModel.Meta):
        verbose_name_plural = "Categories"
        indexes = [models.Index(fields=['slug'])]

    def save(self, *args, **kwargs):
        self.slug = generate_unique_slug(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Tag(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    def save(self, *args, **kwargs):
        self.slug = generate_unique_slug(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# --- Product and Variant Architecture ---

class Attribute(BaseModel):
    """ Represents a product attribute like 'Color' or 'Size'. """
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class AttributeValue(BaseModel):
    """ Represents a value for an attribute, e.g., 'Red' for 'Color'. """
    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name='values')
    value = models.CharField(max_length=100)

    class Meta(BaseModel.Meta):
        unique_together = [['attribute', 'value']]

    def __str__(self):
        return f"{self.attribute.name}: {self.value}"

class Product(BaseModel, SeoModel):
    """
    Acts as a template for product variants. Contains shared information like
    name, description, and category. It is NOT the sellable item itself if variants exist.
    """
    name = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    tags = models.ManyToManyField(Tag, blank=True, related_name='products')
    
    # Generic images for the product, variants can have their own specific images.
    main_image = models.ForeignKey(
        Image, null=True, blank=True, on_delete=models.SET_NULL, related_name='main_image_for_products'
    )
    additional_images = models.ManyToManyField(Image, blank=True, related_name='products')
    
    # The attributes available for this product's variants (e.g., this shirt comes in 'Color' and 'Size')
    attributes = models.ManyToManyField(Attribute, blank=True)

    is_featured = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta(BaseModel.Meta):
        indexes = [models.Index(fields=['slug']), models.Index(fields=['is_active', 'is_featured'])]
        ordering = ['name']

    def save(self, *args, **kwargs):
        self.slug = generate_unique_slug(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class ProductVariant(BaseModel):
    """
    Represents a specific, sellable version of a Product.
    This is the model that holds the SKU, price, and stock information.
    """
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    attribute_values = models.ManyToManyField(AttributeValue, related_name='variants')

    name = models.CharField(max_length=255, blank=True, help_text="Variant name, e.g., 'Red, Large'. Auto-generated if blank.")
    sku = models.CharField(max_length=50, unique=True, blank=True, null=True, help_text="Stock Keeping Unit")
    price = models.DecimalField(max_digits=12, decimal_places=2, help_text="The price of this specific variant.")
    # For more complex pricing (e.g., purchase price), you could add a ForeignKey to a Price model here.
    
    image = models.ForeignKey(
        Image, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="Variant-specific image. Falls back to parent product's image if not set."
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta(BaseModel.Meta):
        # Ensures that you can't have two variants of the same product with the exact same attributes
        # This will require logic in your form/admin to handle the M2M relationship correctly before saving.
        ordering = ['sku']

    def save(self, *args, **kwargs):
        if not self.name and self.pk: # Only generate name if not provided and instance is saved
            values = self.attribute_values.select_related('attribute').order_by('attribute__name')
            self.name = ", ".join([f"{v.value}" for v in values])
        super().save(*args, **kwargs)

    def __str__(self):
        variant_name = self.name or f"Variant {str(self.id)[:4]}"
        return f"{self.product.name} ({variant_name})"

    def get_display_image(self):
        """Returns the variant's image, or falls back to the parent product's main image."""
        if self.image:
            return self.image
        if self.product.main_image:
            return self.product.main_image
        return None # Or a placeholder image

# --- User and Customer Models ---

class CustomerProfile(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    # Consider using `django-phonenumber-field` for robust phone number validation.
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    default_shipping_address = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Profile for {self.user.username}"

class Wishlist(BaseModel):
    """ A user's wishlist. """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wishlist')
    products = models.ManyToManyField(ProductVariant, blank=True, related_name='wishlists')

    def __str__(self):
        return f"Wishlist for {self.user.username}"


# --- Inventory, Warehouse, and Shipping ---

class Warehouse(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def save(self, *args, **kwargs):
        self.slug = generate_unique_slug(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Stock(BaseModel):
    """
    Inventory level for a specific ProductVariant at a specific Warehouse.
    """
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='stock_records')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_records')
    quantity = models.IntegerField(default=0, help_text="Total physical quantity on hand")
    reserved_quantity = models.IntegerField(default=0, help_text="Quantity reserved for open orders")

    class Meta(BaseModel.Meta):
        unique_together = [['product_variant', 'warehouse']]

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity

    def __str__(self):
        return f"{self.available_quantity} available for {self.product_variant} at {self.warehouse.name}"

class StockMovement(BaseModel):
    """ An audit log for every change in stock for a ProductVariant. """
    class MovementType(models.TextChoices):
        SALE = 'sale', 'Sale (-)'
        PURCHASE = 'purchase', 'Purchase (+)'
        ADJUSTMENT = 'adjustment', 'Manual Adjustment (+/-)'
        RETURN = 'return', 'Customer Return (+)'
        TRANSFER_OUT = 'transfer_out', 'Warehouse Transfer Out (-)'
        TRANSFER_IN = 'transfer_in', 'Warehouse Transfer In (+)'

    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    quantity_changed = models.IntegerField(help_text="Positive for stock in, negative for stock out")
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    related_order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.movement_type}: {self.quantity_changed} x {self.product_variant} at {self.warehouse.name}"

class ShippingMethod(BaseModel):
    """ A shipping option for customers to choose. """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    # Consider using django-money for multi-currency sites
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='KZT')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.price} {self.currency})"


# --- Cart, Sales, and E-commerce Models ---

class Cart(BaseModel):
    """ A shopping cart, can be linked to a user or an anonymous session. """
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='carts')
    session_key = models.CharField(max_length=40, null=True, blank=True, db_index=True)

    def __str__(self):
        if self.user:
            return f"Cart for {self.user.username}"
        return f"Anonymous Cart (Session: {self.session_key})"
    
    @property
    def subtotal(self):
        """Calculates the total price of all items in the cart."""
        return self.items.aggregate(
            subtotal=Sum(F('quantity') * F('product_variant__price'))
        )['subtotal'] or Decimal('0.00')

class CartItem(BaseModel):
    """ An item within a shopping cart. """
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1)

    class Meta(BaseModel.Meta):
        unique_together = [['cart', 'product_variant']]

    @property
    def total_price(self):
        return self.quantity * self.product_variant.price

    def __str__(self):
        return f"{self.quantity} x {self.product_variant} in {self.cart}"


class Order(BaseModel):
    class OrderStatus(models.TextChoices):
        PENDING_PAYMENT = 'pending_payment', 'Pending Payment'
        PROCESSING = 'processing', 'Processing'
        SHIPPED = 'shipped', 'Shipped'
        DELIVERED = 'delivered', 'Delivered'
        CANCELLED = 'cancelled', 'Cancelled'
        REFUNDED = 'refunded', 'Refunded'

    order_number = models.CharField(max_length=100, unique=True, blank=True, editable=False)
    customer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='orders')
    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.PENDING_PAYMENT, db_index=True)
    
    # Pricing details
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='KZT')
    
    # Shipping details
    shipping_method = models.ForeignKey(ShippingMethod, on_delete=models.SET_NULL, null=True, blank=True)
    shipping_address = models.TextField()
    billing_address = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"ORD-{timezone.now().strftime('%Y%m')}-{str(self.id)[:6].upper()}"
        self.total_amount = self.subtotal + self.shipping_cost # Simplified calculation
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order {self.order_number} ({self.status})"

class OrderItem(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='order_items')
    quantity = models.PositiveIntegerField(default=1)
    # Store price at time of purchase to prevent changes from affecting historical orders
    price_per_unit = models.DecimalField(max_digits=12, decimal_places=2)
    
    @property
    def total_price(self):
        return self.quantity * self.price_per_unit

    def __str__(self):
        return f"{self.quantity} x {self.product_variant} in Order {self.order.order_number}"

class Payment(BaseModel):
    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESSFUL = 'successful', 'Successful'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True)
    payment_method = models.CharField(max_length=50, help_text="e.g., Credit Card, Kaspi, Bank Transfer")
    transaction_id = models.CharField(max_length=255, blank=True, null=True, help_text="ID from payment gateway")
    
    def __str__(self):
        return f"Payment of {self.amount} for Order {self.order.order_number} ({self.status})"


# --- Marketing and Engagement Models ---

class Review(BaseModel):
    # Reviews are typically for a product in general, not a specific variant.
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='reviews')
    rating = models.PositiveSmallIntegerField(choices=[(i, f"{i} Stars") for i in range(1, 6)])
    comment = models.TextField()
    is_approved = models.BooleanField(default=True, help_text="Moderators can unapprove reviews")

    class Meta(BaseModel.Meta):
        unique_together = [['product', 'user']]

    def __str__(self):
        return f"Review for {self.product.name} by {self.user.username}"

class Discount(BaseModel):
    code = models.CharField(max_length=50, unique=True, help_text="e.g., 'SUMMER20'")
    description = models.CharField(max_length=255)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    is_percentage = models.BooleanField(default=False, help_text="Is the value a percentage? If not, it's a fixed amount.")
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True, db_index=True)
    
    def __str__(self):
        return f"Discount {self.code}"


# --- Operational Models (Original `WorkerProductAudit` preserved) ---

class WorkerProductAudit(BaseModel):
    # Note: This audits a parent Product. For variant-level audits, a new model
    # linking to ProductVariant would be necessary.
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='worker_audit_details')
    last_audited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audited_products')
    quantity_recorded = models.PositiveIntegerField(null=True, blank=True)
    photo_taken = models.ForeignKey(Image, on_delete=models.SET_NULL, null=True, blank=True, limit_choices_to={'type': Image.ImageType.AUDIT})
    is_completed = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if self.quantity_recorded is not None and self.photo_taken is not None:
            if not self.is_completed:
                self.is_completed = True
                self.completed_at = timezone.now()
        else:
            if self.is_completed: 
                self.is_completed = False
                self.completed_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        status = "Completed" if self.is_completed else "Pending"
        return f"Audit for {self.product.name} - {status}"


