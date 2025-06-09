Of course. Here is a comprehensive, updated models.py file that incorporates the suggested improvements and adds new models for a fully functional e-commerce and inventory management website.

Key Improvements and Additions:

SEO Fields: An abstract SeoModel has been created and integrated into Product and Category to provide fields like meta_title and meta_description without repeating code.

User/Customer Management: A CustomerProfile model is added to extend the built-in User model for storing customer-specific data.

E-commerce Flow:

Order: Represents a customer's order.

OrderItem: Represents a line item within an order, capturing the product and price at the time of purchase.

Payment: Tracks payment details and status for each order.

Advanced Inventory: A StockMovement model creates a detailed audit log for every change in stock quantity, essential for tracking and accountability.

Marketing & Engagement:

Review: Allows users to leave product ratings and comments.

Discount: A model to manage promotional codes and sales.

Model Refinements:

Product.main_image: The confusing is_main boolean on the Image model has been replaced with a direct ForeignKey from Product to Image. This is a much cleaner, more explicit, and bug-free way to manage the main image.

Comments & Recommendations: Added comments suggesting powerful libraries like django-money and django-phonenumber-field where appropriate.

Order numbering: A simple, robust method for generating unique order numbers is included in the Order.save() method.

models.py (Fully Updated and Expanded)
import uuid
import os
from decimal import Decimal

from django.db import models
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
    class ImageType(models.TextChoices):
        CATEGORY = 'category', 'Category Photo'
        PRODUCT = 'product', 'Product Photo'
        BARCODE = 'barcode', 'Barcode'
        QRCODE = 'qrcode', 'QR Code'
        LOGO = 'logo', 'Logo'
        AUDIT = 'audit', 'Audit Photo'

    name = models.CharField(max_length=255, db_index=True, blank=True, null=True)
    file_path = models.ImageField(upload_to='images/')
    alt_text = models.CharField(max_length=255, help_text="Text description for accessibility and SEO")
    type = models.CharField(max_length=20, choices=ImageType.choices, default=ImageType.PRODUCT, db_index=True)
    # Metadata fields
    resolution = models.CharField(max_length=50, blank=True, null=True, editable=False)
    size = models.PositiveIntegerField(help_text="Size in KB", blank=True, null=True, editable=False)
    format = models.CharField(max_length=10, blank=True, null=True, editable=False)

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if (is_new or 'file_path' in kwargs.get('update_fields', [])) and self.file_path:
            try:
                img_path = self.file_path.path
                with PILImage.open(img_path) as img:
                    # Optimize and save image
                    max_size = (1920, 1080)
                    img.thumbnail(max_size, PILImage.Resampling.LANCZOS)
                    final_img = img.convert('RGB') if img.mode not in ('RGB', 'L') else img
                    final_img.save(img_path, format='JPEG', quality=85, optimize=True)
                
                # Update metadata
                with PILImage.open(img_path) as final_img:
                    res = f"{final_img.width}x{final_img.height}"
                    fmt = final_img.format
                    sz = os.path.getsize(img_path) // 1024
                    Image.objects.filter(pk=self.pk).update(resolution=res, size=sz, format=fmt)
            except (FileNotFoundError, Exception) as e:
                # Log this error properly in a real application
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

class Product(BaseModel, SeoModel):
    name = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    article_number = models.CharField(max_length=50, blank=True, null=True, help_text="SKU", db_index=True)
    description = models.TextField(blank=True, null=True)
    short_description = models.CharField(max_length=255, blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    tags = models.ManyToManyField(Tag, blank=True, related_name='products')
    
    # Replaces the `is_main` flag on Image for a more robust design
    main_image = models.ForeignKey(
        Image, null=True, blank=True, on_delete=models.SET_NULL, related_name='main_image_for_products'
    )
    additional_images = models.ManyToManyField(Image, blank=True, related_name='products')

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

    def get_main_image(self):
        """Returns the main image, falling back to the first additional image or None."""
        if self.main_image:
            return self.main_image
        return self.additional_images.first()

class Price(BaseModel):
    class PriceType(models.TextChoices):
        SELLING = 'selling', 'Selling Price'
        PURCHASE = 'purchase', 'Purchase Price'
        REGULAR = 'regular', 'Regular Price'
        DISCOUNT = 'discount', 'Discount Price'

    class Currency(models.TextChoices):
        # Consider using a dedicated library like `django-money` for production
        KZT = 'KZT', 'Казахстанский тенге'
        USD = 'USD', 'Доллар США'
        EUR = 'EUR', 'Евро'
        RUB = 'RUB', 'Российский рубль'

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='prices')
    price_type = models.CharField(max_length=20, choices=PriceType.choices, default=PriceType.REGULAR, db_index=True)
    currency = models.CharField(max_length=10, choices=Currency.choices, default=Currency.KZT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta(BaseModel.Meta):
        unique_together = [['product', 'price_type', 'currency']]
        ordering = ['-is_active', 'price_type', 'amount']
        indexes = [models.Index(fields=['product', 'price_type', 'is_active'])]

    def __str__(self):
        return f"{self.product.name}: {self.amount} {self.currency} ({self.get_price_type_display()})"


# --- User and Counterparty Models ---

class CustomerProfile(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    # Consider using a library like `django-phonenumber-field` for production
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    default_shipping_address = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Profile for {self.user.username}"

class Counterparty(BaseModel):
    class CounterpartyType(models.TextChoices):
        SUPPLIER = 'supplier', 'Supplier'
        CUSTOMER = 'customer', 'Customer'
        TRANSPORT = 'transport', 'Transport Company'
        OTHER = 'other', 'Other'

    name = models.CharField(max_length=255, db_index=True)
    counterparty_type = models.CharField(max_length=20, choices=CounterpartyType.choices, db_index=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return f"{self.name} ({self.get_counterparty_type_display()})"


# --- Inventory and Warehouse Models ---

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
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_records')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_records')
    quantity = models.PositiveIntegerField(default=0, help_text="Total physical quantity")
    reserved_quantity = models.PositiveIntegerField(default=0, help_text="Quantity reserved for open orders")

    class Meta(BaseModel.Meta):
        unique_together = [['product', 'warehouse']]

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity

    def __str__(self):
        return f"{self.product.name} at {self.warehouse.name}: {self.available_quantity} available"

class StockMovement(BaseModel):
    class MovementType(models.TextChoices):
        SALE = 'sale', 'Sale (-)'
        PURCHASE = 'purchase', 'Purchase (+)'
        ADJUSTMENT = 'adjustment', 'Manual Adjustment (+/-)'
        RETURN = 'return', 'Customer Return (+)'
        TRANSFER_OUT = 'transfer_out', 'Warehouse Transfer Out (-)'
        TRANSFER_IN = 'transfer_in', 'Warehouse Transfer In (+)'

    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    quantity_changed = models.IntegerField(help_text="Positive for stock in, negative for stock out")
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    related_order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.movement_type}: {self.quantity_changed} x {self.product.name} at {self.warehouse.name}"


# --- Sales and E-commerce Models ---

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
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=10, choices=Price.Currency.choices, default=Price.Currency.KZT)
    shipping_address = models.TextField()
    billing_address = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"ORD-{timezone.now().strftime('%Y%m')}-{str(self.id)[:6].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order {self.order_number} ({self.status})"

class OrderItem(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='order_items')
    quantity = models.PositiveIntegerField(default=1)
    # Store price at time of purchase to prevent changes from affecting historical orders
    price_per_unit = models.DecimalField(max_digits=12, decimal_places=2)
    
    @property
    def total_price(self):
        return self.quantity * self.price_per_unit

    def __str__(self):
        return f"{self.quantity} x {self.product.name} in Order {self.order.order_number}"

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

