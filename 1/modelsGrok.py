import uuid
import os
import logging
from decimal import Decimal

from django.db import models, transaction
from django.db.models import F, Sum, Q, Count, CheckConstraint
from django.utils.text import slugify
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from django.core.serializers import serialize
from PIL import Image as PILImage
from moneyed import Money, KZT
from django_money.fields import MoneyField
from parler.models import TranslatableModel, TranslatedFields

logger = logging.getLogger(__name__)

# --- Helper Function for Unique Slugs ---
def generate_unique_slug(instance, source_field='name', slug_field='slug'):
    """Generate a unique slug based on source_field, appending a number if needed."""
    if getattr(instance, slug_field) and not instance._state.adding:
        return getattr(instance, slug_field)
    base_slug = slugify(getattr(instance, source_field, str(instance.id)[:8]))
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
    """Abstract base model with UUID, timestamps, and default ordering."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

class SeoModel(models.Model):
    """Abstract model for SEO fields."""
    meta_title = models.CharField(max_length=255, blank=True, null=True, help_text="SEO title (falls back to name).")
    meta_description = models.CharField(max_length=300, blank=True, null=True, help_text="SEO description.")
    meta_keywords = models.CharField(max_length=255, blank=True, null=True, help_text="Comma-separated SEO keywords.")

    class Meta:
        abstract = True

# --- Core Entity Models ---
class Image(BaseModel):
    """Model for storing images with type and accessibility metadata."""
    class ImageType(models.TextChoices):
        CATEGORY = 'category', 'Category Photo'
        PRODUCT = 'product', 'Product Photo'
        VARIANT = 'variant', 'Product Variant Photo'
        AUDIT = 'audit', 'Audit Photo'

    name = models.CharField(max_length=255, db_index=True, blank=True, null=True)
    file_path = models.ImageField(upload_to='images/')
    alt_text = models.CharField(max_length=255, help_text="Text description for accessibility and SEO")
    type = models.CharField(max_length=20, choices=ImageType.choices, default=ImageType.PRODUCT, db_index=True)

    def save(self, *args, **kwargs):
        """Save image with compression if dimensions exceed 1000x1000."""
        super().save(*args, **kwargs)
        if self.file_path:
            try:
                img = PILImage.open(self.file_path.path)
                if img.size[0] > 1000 or img.size[1] > 1000:
                    img.thumbnail((1000, 1000))
                    img.save(self.file_path.path, quality=85)
            except Exception as e:
                logger.error(f"Failed to process image {self.file_path.name}: {e}")

    def __str__(self):
        return self.alt_text or os.path.basename(self.file_path.name)

class Category(BaseModel, SeoModel, TranslatableModel):
    """Category model with hierarchy and translations."""
    translations = TranslatedFields(
        name=models.CharField(max_length=255, db_index=True),
        description=models.TextField(blank=True, null=True)
    )
    slug = models.SlugField(max_length=255, unique=True, blank=True)
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
    """Tag model for product categorization."""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ['name']

    def save(self, *args, **kwargs):
        self.slug = generate_unique_slug(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

# --- Product and Variant Architecture ---
class Attribute(BaseModel):
    """Model for product attributes (e.g., Color, Size)."""
    name = models.CharField(max_length=100, unique=True)

    class Meta(BaseModel.Meta):
        ordering = ['name']

    def __str__(self):
        return self.name

class AttributeValue(BaseModel):
    """Values for product attributes."""
    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name='values')
    value = models.CharField(max_length=100)

    class Meta(BaseModel.Meta):
        unique_together = [['attribute', 'value']]
        ordering = ['attribute__name', 'value']

    def __str__(self):
        return f"{self.attribute.name}: {self.value}"

class ProductManager(models.Manager):
    """Custom manager for Product model."""
    def active(self):
        return self.filter(is_active=True)

class Product(BaseModel, SeoModel, TranslatableModel):
    """Product model with translations and SEO."""
    translations = TranslatedFields(
        name=models.CharField(max_length=255, db_index=True),
        description=models.TextField(blank=True, null=True)
    )
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    tags = models.ManyToManyField(Tag, blank=True, related_name='products')
    main_image = models.ForeignKey(Image, null=True, blank=True, on_delete=models.SET_NULL, related_name='main_image_for_products')
    additional_images = models.ManyToManyField(Image, blank=True, related_name='products')
    attributes = models.ManyToManyField(Attribute, blank=True, help_text="Attributes for variants (e.g., Color, Size)")
    is_featured = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    objects = ProductManager()

    class Meta(BaseModel.Meta):
        indexes = [models.Index(fields=['slug']), models.Index(fields=['is_active', 'is_featured'])]
        ordering = ['translations__name']

    def save(self, *args, **kwargs):
        self.slug = generate_unique_slug(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class ProductVariantManager(models.Manager):
    """Custom manager for ProductVariant with bulk operations."""
    def bulk_set_price(self, variant_ids, value, is_percentage=False):
        """Update prices for variants (fixed amount or percentage)."""
        variants = self.filter(pk__in=variant_ids)
        if is_percentage:
            multiplier = Decimal(1) + (Decimal(value) / Decimal(100))
            return variants.update(price=F('price') * multiplier)
        return variants.update(price=Decimal(value))

class ProductVariant(BaseModel):
    """Model for product variants with unique attribute combinations."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    attribute_values = models.ManyToManyField(AttributeValue, related_name='variants')
    sku = models.CharField(max_length=50, unique=True, blank=True, null=True, help_text="Stock Keeping Unit")
    price = MoneyField(max_digits=12, decimal_places=2, default_currency='KZT')
    image = models.ForeignKey(Image, null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True, db_index=True)

    objects = ProductVariantManager()

    class Meta(BaseModel.Meta):
        ordering = ['sku']
        constraints = [
            CheckConstraint(
                check=Q(attribute_values__isnull=False),
                name='non_empty_attribute_values'
            )
        ]

    def clean(self):
        """Validate unique attribute value combinations for the product."""
        if not self.pk or not self.product_id:
            return
        value_ids = set(self.attribute_values.values_list('pk', flat=True))
        if not value_ids:
            raise ValidationError("Product variant must have at least one attribute value.")
        conflicting_variants = ProductVariant.objects.filter(product=self.product).exclude(pk=self.pk)
        conflicting_variants = conflicting_variants.annotate(num_values=Count('attribute_values')).filter(num_values=len(value_ids))
        for value_id in value_ids:
            conflicting_variants = conflicting_variants.filter(attribute_values__pk=value_id)
        if conflicting_variants.exists():
            raise ValidationError(f'A variant with these attribute values already exists for product "{self.product.name}".')

    def save(self, *args, **kwargs):
        """Generate SKU and validate before saving."""
        if not self.sku:
            values = ''.join(v.value[:3] for v in self.attribute_values.all())[:8] if self.attribute_values.exists() else str(self.id)[:8]
            self.sku = f"{self.product.slug[:8].upper()}-{values}"
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        """Generate display name from attribute values."""
        if not self.pk:
            return "New Variant"
        values = self.attribute_values.select_related('attribute').order_by('attribute__name')
        return ", ".join([v.value for v in values])

    def __str__(self):
        return f"{self.product.name} ({self.display_name or f'Variant {str(self.id)[:4]}'})"

    def get_display_image(self):
        return self.image or self.product.main_image

# --- User, Customer, and Address Models ---
class Address(BaseModel):
    """Reusable structured address model."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    class AddressType(models.TextChoices):
        SHIPPING = 'shipping', 'Shipping'
        BILLING = 'billing', 'Billing'
    address_type = models.CharField(max_length=10, choices=AddressType.choices, default=AddressType.SHIPPING)
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Kazakhstan')
    city = models.CharField(max_length=100)
    street_address = models.CharField(max_length=255)
    postal_code = models.CharField(max_length=20)
    is_default = models.BooleanField(default=False, help_text="Default address for this type.")

    def save(self, *args, **kwargs):
        """Ensure only one default address per type per user."""
        if self.is_default:
            Address.objects.filter(user=self.user, address_type=self.address_type).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name}, {self.street_address}, {self.city}"

class CustomerProfile(BaseModel):
    """User profile with contact and default addresses."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    default_shipping_address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    default_billing_address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    def __str__(self):
        return f"Profile for {self.user.username}"

class Wishlist(BaseModel):
    """User wishlist for product variants."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wishlist')
    products = models.ManyToManyField(ProductVariant, blank=True, related_name='wishlists')

    def __str__(self):
        return f"Wishlist for {self.user.username}"

# --- Inventory, Warehouse, and Shipping ---
class Warehouse(BaseModel):
    """Warehouse model for stock management."""
    name = models.CharField(max_length=255, unique=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)

    def __str__(self):
        return self.name

class Stock(BaseModel):
    """Stock record for a product variant in a warehouse."""
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='stock_records')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_records')
    quantity = models.IntegerField(default=0, help_text="Total physical quantity")
    reserved_quantity = models.IntegerField(default=0, help_text="Quantity reserved for orders")

    class Meta(BaseModel.Meta):
        unique_together = [['product_variant', 'warehouse']]

    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity

class StockMovement(BaseModel):
    """Audit log for stock changes."""
    class MovementType(models.TextChoices):
        SALE = 'sale', 'Sale (-)'
        PURCHASE = 'purchase', 'Purchase (+)'
        ADJUSTMENT = 'adjustment', 'Adjustment (+/-)'
        RETURN = 'return', 'Return (+)'
        TRANSFER_OUT = 'transfer_out', 'Transfer Out (-)'
        TRANSFER_IN = 'transfer_in', 'Transfer In (+)'

    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT)
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT)
    quantity_changed = models.IntegerField(help_text="Positive for stock in, negative for stock out")
    movement_type = models.CharField(max_length=20, choices=MovementType.choices, db_index=True)
    related_order = models.ForeignKey('Order', on_delete=models.SET_NULL, null=True, blank=True)
    related_audit = models.ForeignKey('StockAudit', on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.movement_type}: {self.quantity_changed} x {self.product_variant} at {self.warehouse.name}"

class ShippingMethod(BaseModel):
    """Shipping option for customers."""
    name = models.CharField(max_length=100)
    price = MoneyField(max_digits=10, decimal_places=2, default_currency='KZT')
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.price})"

# --- Cart, Order, and Payment Models ---
class Cart(BaseModel):
    """Shopping cart for users or anonymous sessions."""
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='carts')
    session_key = models.CharField(max_length=40, null=True, blank=True, db_index=True)

    def __str__(self):
        if self.user:
            return f"Cart for {self.user.username}"
        return f"Anonymous Cart (Session: {self.session_key})"

    @property
    def subtotal(self):
        return self.items.aggregate(subtotal=Sum(F('quantity') * F('product_variant__price')))['subtotal'] or Money(0, 'KZT')

class CartItem(BaseModel):
    """Item in a shopping cart."""
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1)

    class Meta(BaseModel.Meta):
        unique_together = [['cart', 'product_variant']]

    @property
    def total_price(self):
        return Money(self.quantity * self.product_variant.price.amount, self.product_variant.price.currency)

    def __str__(self):
        return f"{self.quantity} x {self.product_variant} in {self.cart}"

class Order(BaseModel):
    """Customer order with status and financial details."""
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
    subtotal = MoneyField(max_digits=12, decimal_places=2, default_currency='KZT')
    shipping_cost = MoneyField(max_digits=12, decimal_places=2, default_currency='KZT')
    discount_amount = MoneyField(max_digits=12, decimal_places=2, default_currency='KZT')
    total_amount = MoneyField(max_digits=12, decimal_places=2, default_currency='KZT')
    shipping_address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name='shipping_orders')
    billing_address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name='billing_orders', null=True, blank=True)
    shipping_method = models.ForeignKey(ShippingMethod, on_delete=models.SET_NULL, null=True, blank=True)
    discounts = models.ManyToManyField('Discount', blank=True, related_name='orders')
    notes = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"ORD-{timezone.now().strftime('%Y%m')}-{str(self.id)[:6].upper()}"
        self.total_amount = max(Money(0, self.subtotal.currency), (self.subtotal + self.shipping_cost) - self.discount_amount)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order {self.order_number} ({self.status})"

class OrderItem(BaseModel):
    """Item in an order with snapshot of product data."""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='order_items')
    quantity = models.PositiveIntegerField(default=1)
    price_per_unit = MoneyField(max_digits=12, decimal_places=2, default_currency='KZT')
    product_snapshot = models.JSONField(null=True, blank=True, help_text="Snapshot of product data at order time")

    def save(self, *args, **kwargs):
        if not self.product_snapshot:
            self.product_snapshot = {
                'name': self.product_variant.product.name,
                'variant_display_name': self.product_variant.display_name,
                'sku': self.product_variant.sku,
                'price': str(self.product_variant.price)
            }
        super().save(*args, **kwargs)

    @property
    def total_price(self):
        return Money(self.quantity * self.price_per_unit.amount, self.price_per_unit.currency)

    def __str__(self):
        return f"{self.quantity} x {self.product_variant} in Order {self.order.order_number}"

class Payment(BaseModel):
    """Payment record for an order."""
    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESSFUL = 'successful', 'Successful'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    amount = MoneyField(max_digits=12, decimal_places=2, default_currency='KZT')
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True)
    payment_method = models.CharField(max_length=50, help_text="e.g., Credit Card, Kaspi, Bank Transfer")
    transaction_id = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Payment of {self.amount} for Order {self.order.order_number} ({self.status})"

# --- Marketing and Engagement Models ---
class DiscountManager(models.Manager):
    """Manager for discounts with active/expired filtering."""
    def get_active(self):
        """Return active discounts within date range."""
        now = timezone.now()
        return self.filter(is_active=True, start_date__lte=now, end_date__gte=now)

    def deactivate_expired(self):
        """Deactivate expired discounts."""
        now = timezone.now()
        expired_discounts = self.filter(end_date__lt=now, is_active=True)
        return expired_discounts.update(is_active=False)

class Discount(BaseModel):
    """Discount model with usage limits and conditions."""
    code = models.CharField(max_length=50, unique=True, help_text="e.g., SUMMER20")
    description = models.CharField(max_length=255, blank=True)
    discount_value = MoneyField(max_digits=10, decimal_places=2, default_currency='KZT')
    is_percentage = models.BooleanField(default=False)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True, db_index=True)
    min_order_value = MoneyField(max_digits=12, decimal_places=2, default_currency='KZT', null=True, blank=True)
    applies_to_products = models.ManyToManyField(Product, blank=True)
    applies_to_categories = models.ManyToManyField(Category, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True, help_text="Max number of uses")
    used_count = models.PositiveIntegerField(default=0)
    applies_to_users = models.ManyToManyField(User, blank=True, help_text="Restrict to specific users")

    objects = DiscountManager()

    def is_valid(self):
        """Check if discount is active and within date range."""
        now = timezone.now()
        if not (self.is_active and self.start_date <= now <= self.end_date):
            return False
        if self.max_uses and self.used_count >= self.max_uses:
            return False
        return True

    def __str__(self):
        value_str = f"{self.discount_value}%" if self.is_percentage else str(self.discount_value)
        return f"Discount {self.code} ({value_str})"

class Review(BaseModel):
    """User review for a product."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='reviews')
    rating = models.PositiveSmallIntegerField(choices=[(i, f"{i} Stars") for i in range(1, 6)])
    comment = models.TextField()
    is_approved = models.BooleanField(default=True)

    class Meta(BaseModel.Meta):
        unique_together = [['product', 'user']]

    def __str__(self):
        return f"Review for {self.product.name} by {self.user.username}"

# --- Operational Models ---
class StockAudit(BaseModel):
    """Audit record for stock verification."""
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='audits')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='audits')
    audited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='conducted_audits')
    quantity_before_audit = models.IntegerField()
    quantity_recorded = models.IntegerField()
    photo_taken = models.ForeignKey(Image, on_delete=models.SET_NULL, null=True, blank=True, limit_choices_to={'type': Image.ImageType.AUDIT})
    notes = models.TextField(blank=True, null=True)
    is_completed = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    @property
    def quantity_discrepancy(self):
        return self.quantity_recorded - self.quantity_before_audit

    @transaction.atomic
    def complete_audit(self):
        """Complete audit, update stock, and create movement record."""
        if self.is_completed:
            return False
        discrepancy = self.quantity_discrepancy
        stock, _ = Stock.objects.get_or_create(product_variant=self.product_variant, warehouse=self.warehouse)
        Stock.objects.filter(pk=stock.pk).update(quantity=F('quantity') + discrepancy)
        if discrepancy != 0:
            StockMovement.objects.create(
                product_variant=self.product_variant,
                warehouse=self.warehouse,
                quantity_changed=discrepancy,
                movement_type=StockMovement.MovementType.ADJUSTMENT,
                notes=f"Stock audit {self.id}",
                related_audit=self
            )
        self.is_completed = True
        self.completed_at = timezone.now()
        self.save(update_fields=['is_completed', 'completed_at'])
        return True

    def __str__(self):
        status = "Completed" if self.is_completed else "Pending"
        return f"Audit for {self.product_variant} at {self.warehouse.name} - {status}"

# --- Analytics Model ---
class ProductView(BaseModel):
    """Track product views for analytics."""
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='views')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    session_key = models.CharField(max_length=40, null=True, blank=True, db_index=True)

    def __str__(self):
        return f"View of {self.product.name} by {self.user.username if self.user else 'Anonymous'}"

# --- Signals ---
@receiver(user_logged_in)
@transaction.atomic
def merge_anonymous_cart_with_user_cart(sender, request, user, **kwargs):
    """Merge anonymous cart with user cart on login."""
    try:
        session_key = request.session.session_key
        if not session_key:
            return
        anonymous_cart = Cart.objects.get(session_key=session_key, user__isnull=True)
        try:
            user_cart = Cart.objects.get(user=user)
            for item in anonymous_cart.items.all():
                existing_item, created = CartItem.objects.get_or_create(
                    cart=user_cart,
                    product_variant=item.product_variant,
                    defaults={'quantity': item.quantity}
                )
                if not created:
                    existing_item.quantity = F('quantity') + item.quantity
                    existing_item.save(update_fields=['quantity'])
            anonymous_cart.delete()
        except Cart.DoesNotExist:
            anonymous_cart.user = user
            anonymous_cart.session_key = None
            anonymous_cart.save(update_fields=['user', 'session_key'])
    except Cart.DoesNotExist:
        return
    except Exception as e:
        logger.error(f"Failed to merge cart for user {user.username}: {e}")