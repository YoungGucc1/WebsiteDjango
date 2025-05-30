# --- START OF FILE models.py ---

import uuid
from django.db import models
from django.utils.text import slugify
from django.utils import timezone
from PIL import Image as PILImage
import os
from decimal import Decimal
from django.conf import settings # For User model

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
        base_slug = str(instance.id)[:8] if instance.id else uuid.uuid4().hex[:8]


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

# --- Abstract Base Model ---
class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

# --- Image Model ---
class Image(BaseModel):
    class ImageType(models.TextChoices):
        CATEGORY = 'category', 'Category Photo'
        PRODUCT = 'product', 'Product Photo'
        BARCODE = 'barcode', 'Barcode'
        QRCODE = 'qrcode', 'QR Code'
        PREVIEW = 'preview', 'Preview'
        PACKAGING = 'packaging', 'Packaging'
        LOGO = 'logo', 'Logo'
        CONTRAGENT = 'contragent', 'Contragent Photo/Logo' # New type for Contragent

    name = models.CharField(max_length=255, db_index=True, blank=True, null=True)
    file_path = models.ImageField(upload_to='images/')
    description = models.TextField(blank=True, null=True)
    resolution = models.CharField(max_length=50, blank=True, null=True, editable=False)
    size = models.PositiveIntegerField(help_text="Size in KB", blank=True, null=True, editable=False)
    format = models.CharField(max_length=10, blank=True, null=True, editable=False)
    alt_text = models.CharField(max_length=255, blank=True, null=True, help_text="Text description for accessibility and SEO")
    type = models.CharField(
        max_length=20,
        choices=ImageType.choices,
        default=ImageType.PRODUCT,
        help_text="Type of the image",
        db_index=True
    )
    is_main = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Mark this image as the main image for the product/category/etc."
    )

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        original_is_main_state = None

        if not is_new and self.pk:
            try:
                original_instance = Image.objects.get(pk=self.pk)
                original_is_main_state = original_instance.is_main
            except Image.DoesNotExist:
                pass # Should not happen if not is_new, but proceed

        # Process file if it's new or path changed
        process_file = (is_new or 'file_path' in kwargs.get('update_fields', [])) and self.file_path
        
        if process_file:
            try:
                # Temporarily save to get path if new, or use existing path
                # This part is tricky if the file name changes based on content or instance ID
                # For simplicity, assume self.file_path.path is available or will be after super().save()
                # To make it safer, image processing should happen *after* initial save if new.
                # However, to update metadata (resolution, size) *before* the main save,
                # we might need to open from memory if `self.file_path` is an InMemoryUploadedFile.

                # Let's assume file is on disk or will be after first save for processing.
                # For now, we'll try to process, and if it fails due to path not ready,
                # it might need a post_save signal or two-step save.

                # If it's a new file, we must save it first to get a path for PIL
                if is_new and not self.file_path.path: # Check if path exists
                    # Temporarily save just the file to process it
                    super().save(update_fields=['file_path'] if 'file_path' in kwargs.get('update_fields', []) else None)


                img_path = self.file_path.path
                with PILImage.open(img_path) as img:
                    max_size = (1920, 1080)
                    img_changed = False
                    current_format = img.format

                    if img.width > max_size[0] or img.height > max_size[1]:
                        img.thumbnail(max_size, PILImage.Resampling.LANCZOS)
                        img_changed = True

                    if img.mode not in ('RGB', 'L', 'RGBA'): # Allow RGBA for PNGs
                        if img.mode == 'P' and 'transparency' in img.info: # Palette with transparency
                            img = img.convert('RGBA')
                        else:
                            img = img.convert('RGB')
                        img_changed = True
                    
                    save_kwargs = {'quality': 85, 'optimize': True}
                    save_format = current_format if current_format in ['JPEG', 'PNG', 'GIF'] else 'JPEG'
                    if save_format == 'JPEG' and img.mode == 'RGBA': # JPEG doesn't support alpha
                        img = img.convert('RGB')
                        img_changed = True # Potentially

                    if img_changed:
                        img.save(img_path, format=save_format, **save_kwargs)

                with PILImage.open(img_path) as final_img:
                    self.resolution = f"{final_img.width}x{final_img.height}"
                    self.format = final_img.format
                    self.size = os.path.getsize(img_path) // 1024
            
            except FileNotFoundError:
                print(f"Warning: Could not process image {getattr(self.file_path, 'name', 'N/A')} (initial save). File not found.")
            except Exception as e:
                print(f"Error processing image {getattr(self.file_path, 'name', 'N/A')} (initial save): {e}")
        
        super().save(*args, **kwargs) # Main save operation for all fields

        # Handle is_main logic *after* the instance is saved
        if self.is_main and (is_new or (original_is_main_state is False and self.is_main is True)):
            # If this image is for a product
            if self.type == self.ImageType.PRODUCT and hasattr(self, 'products'):
                for product in self.products.all():
                    product.images.exclude(pk=self.pk).filter(is_main=True, type=self.ImageType.PRODUCT).update(is_main=False)
            # If this image is for a category
            elif self.type == self.ImageType.CATEGORY and hasattr(self, 'category_images'): # Assuming 'category_images' is related_name from Category.image
                 # Category has one image, so if this is main, others of type CATEGORY for *other* categories shouldn't be affected.
                 # This logic might need refinement if a category can have multiple images and only one is main.
                 # For now, if Category.image is ForeignKey, this logic is mostly for Product.
                 pass # ForeignKey handles uniqueness. If M2M, logic similar to Product.
            elif self.type == self.ImageType.CONTRAGENT and hasattr(self, 'contragent_logos'): # related_name from Contragent.logo
                for contragent in self.contragent_logos.all():
                    contragent.logos.exclude(pk=self.pk).filter(is_main=True, type=self.ImageType.CONTRAGENT).update(is_main=False)


    def __str__(self):
        name_part = self.name or os.path.basename(self.file_path.name if self.file_path else f"Image {self.id}")
        return f"{name_part} ({self.get_type_display()})"


# --- Category Model ---
class Category(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    name_2 = models.CharField(max_length=255, blank=True, null=True)
    category_article = models.CharField(max_length=50, blank=True, null=True, help_text="Category article/reference code", db_index=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children', db_index=True)
    image = models.ForeignKey(
        Image,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='category_image_for', # Changed related_name for clarity
        limit_choices_to={'type': Image.ImageType.CATEGORY}
    )

    class Meta(BaseModel.Meta):
        verbose_name_plural = "Categories"
        indexes = [models.Index(fields=['slug']), models.Index(fields=['category_article'])]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(self, 'name', 'slug')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

# --- Tag Model ---
class Tag(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    name_2 = models.CharField(max_length=100, blank=True, null=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta(BaseModel.Meta):
        indexes = [models.Index(fields=['slug'])]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(self, 'name', 'slug')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

# --- Contragent Model (Replaces Customer and Supplier) ---
class Contragent(BaseModel):
    class ContragentType(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        SUPPLIER = 'supplier', 'Supplier'
        EMPLOYEE = 'employee', 'Employee'
        PARTNER = 'partner', 'Partner'
        OTHER = 'other', 'Other'

    name = models.CharField(max_length=255, db_index=True, help_text="Full name or Company name")
    contragent_type = models.CharField(
        max_length=20,
        choices=ContragentType.choices,
        db_index=True
    )
    
    # Optional fields for individuals / contact persons
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    
    email = models.EmailField(db_index=True, blank=True, null=True)
    phone_number = models.CharField(max_length=30, blank=True, null=True)
    
    # Company specific details
    tax_id = models.CharField(max_length=50, blank=True, null=True, db_index=True, help_text="e.g., INN, TIN, VAT ID")
    registration_number = models.CharField(max_length=50, blank=True, null=True, help_text="Company registration number")

    address_legal = models.TextField(blank=True, null=True, help_text="Legal Address")
    address_shipping = models.TextField(blank=True, null=True, help_text="Default Shipping Address")
    address_billing = models.TextField(blank=True, null=True, help_text="Default Billing Address")
    
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='contragent_profile',
        help_text="Link to system user, if applicable (e.g., for employees, or customer portal user)"
    )
    
    logos = models.ManyToManyField(
        Image, 
        blank=True, 
        related_name='contragent_logos',
        limit_choices_to={'type': Image.ImageType.CONTRAGENT}
    )

    notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Contragent"
        verbose_name_plural = "Contragents"
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['contragent_type']),
            models.Index(fields=['tax_id']),
            models.Index(fields=['email']),
        ]

    def __str__(self):
        type_display = self.get_contragent_type_display()
        name_display = self.name
        if not name_display and self.first_name and self.last_name:
            name_display = f"{self.first_name} {self.last_name}"
        elif name_display and self.first_name and self.last_name:
             name_display = f"{self.name} ({self.first_name} {self.last_name})"
        
        return f"{name_display or 'Unnamed Contragent'} [{type_display}]"

    def save(self, *args, **kwargs):
        if not self.name and self.first_name and self.last_name:
            self.name = f"{self.first_name} {self.last_name}"
        super().save(*args, **kwargs)
        
    @property
    def main_logo(self):
        main = self.logos.filter(is_main=True).first()
        return main if main else self.logos.first()

# --- Product Model ---
class Product(BaseModel):
    name = models.CharField(max_length=255, db_index=True)
    name_2 = models.CharField(max_length=255, blank=True, null=True)
    article_number = models.CharField(max_length=50, blank=True, null=True, help_text="Product article/SKU number", db_index=True, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    short_description = models.CharField(max_length=255, blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, db_index=True, related_name='products')
    tags = models.ManyToManyField(Tag, blank=True, related_name='products')
    images = models.ManyToManyField(
        Image, 
        blank=True, 
        related_name='products',
        limit_choices_to={'type__in': [Image.ImageType.PRODUCT, Image.ImageType.PREVIEW, Image.ImageType.PACKAGING]}
    )
    
    unit_display_name = models.CharField(
        max_length=20, 
        blank=True, null=True, 
        default="pcs",
        help_text="Display name for unit (e.g., pcs, kg, pack, m)"
    )
    
    is_featured = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True, help_text="Is this product visible on the site?")
    track_inventory = models.BooleanField(default=True, help_text="Should inventory be tracked for this product?")
    low_stock_threshold = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Threshold for low stock warning (quantity)")

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active', 'is_featured']),
            models.Index(fields=['name']),
            models.Index(fields=['category']),
            models.Index(fields=['article_number']),
        ]
        ordering = ['name']

    def save(self, *args, **kwargs):
        source_for_slug = self.name
        if not source_for_slug and self.article_number:
            source_for_slug = self.article_number

        if not self.slug:
            self.slug = generate_unique_slug(self, source_field='name' if self.name else 'article_number', slug_field='slug')
            # Fallback if both name and article_number are empty somehow
            if not self.slug and self.id: # Ensure ID is set
                 self.slug = str(self.id)[:8]

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.article_number})" if self.article_number else self.name

    @property
    def current_price_display(self):
        now = timezone.now()
        active_price = self.prices.filter(
            is_active=True,
            price_type__in=[Price.PriceType.SELLING, Price.PriceType.REGULAR, Price.PriceType.DISCOUNT],
            valid_from__lte=now,
            valid_to__gte=now
        ).order_by('amount').first()

        if not active_price:
             active_price = self.prices.filter(
                is_active=True,
                price_type__in=[Price.PriceType.SELLING, Price.PriceType.REGULAR, Price.PriceType.DISCOUNT],
                valid_from__isnull=True,
                valid_to__isnull=True
            ).order_by('amount').first()

        if active_price:
            return f"{active_price.amount} {active_price.currency}"
        return "Price not available"

    @property
    def main_image(self):
        main_image = self.images.filter(is_main=True).first()
        if main_image:
            return main_image
        return self.images.order_by('created_at').first()

    @property
    def total_stock(self):
        if not self.track_inventory:
            return "N/A (Inventory not tracked)"
        
        total_agg = StockItem.objects.filter(product=self).aggregate(total_quantity=models.Sum('quantity'))
        quantity = total_agg['total_quantity'] or Decimal('0.00')
        unit = self.unit_display_name or ""
        return f"{quantity} {unit}".strip() if unit else str(quantity)

# --- Price Model ---
class Price(BaseModel):
    class PriceType(models.TextChoices):
        SELLING = 'selling', 'Selling Price'
        PURCHASE = 'purchase', 'Purchase Price'
        REGULAR = 'regular', 'Regular Price'
        DISCOUNT = 'discount', 'Discount Price'
        WHOLESALE = 'wholesale', 'Wholesale Price'
        MSRP = 'msrp', 'Manufacturer Suggested Retail Price'
        OTHER = 'other', 'Other Price'

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='prices')
    price_type = models.CharField(
        max_length=20,
        choices=PriceType.choices,
        default=PriceType.REGULAR,
        db_index=True
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD', help_text="e.g., USD, EUR")
    description = models.CharField(max_length=100, blank=True, null=True)
    valid_from = models.DateTimeField(null=True, blank=True, help_text="Price valid from this date")
    valid_to = models.DateTimeField(null=True, blank=True, help_text="Price valid until this date")
    is_active = models.BooleanField(default=True, help_text="Is this price currently active?")

    class Meta(BaseModel.Meta):
        ordering = ['product', '-is_active', 'price_type', 'amount']
        indexes = [
            models.Index(fields=['product', 'price_type', 'is_active']),
            models.Index(fields=['product', 'is_active', 'valid_from', 'valid_to']),
        ]

    def save(self, *args, **kwargs):
        if self.is_active and self.valid_from is None and self.valid_to is None:
            Price.objects.filter(
                product=self.product,
                price_type=self.price_type,
                currency=self.currency,
                is_active=True,
                valid_from__isnull=True,
                valid_to__isnull=True
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def __str__(self):
        type_display = self.get_price_type_display()
        desc = f" ({self.description})" if self.description else ""
        active_status = "" if self.is_active else " (Inactive)"
        date_range = ""
        if self.valid_from or self.valid_to:
            vf = self.valid_from.strftime('%Y-%m-%d %H:%M') if self.valid_from else "..."
            vt = self.valid_to.strftime('%Y-%m-%d %H:%M') if self.valid_to else "..."
            date_range = f" [{vf} - {vt}]"
        return f"{self.product.name if self.product else 'N/A'}: {self.amount} {self.currency} ({type_display}){desc}{date_range}{active_status}"

# --- Warehouse Model ---
class Warehouse(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, help_text="Is this warehouse operational?")

    class Meta(BaseModel.Meta):
        verbose_name = "Warehouse"
        verbose_name_plural = "Warehouses"
        ordering = ['name']

    def __str__(self):
        return self.name

# --- StockItem Model ---
class StockItem(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_items')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_items')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    last_restocked_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    class Meta(BaseModel.Meta):
        verbose_name = "Stock Item"
        verbose_name_plural = "Stock Items"
        unique_together = [['product', 'warehouse']]
        ordering = ['product__name', 'warehouse__name']
        indexes = [models.Index(fields=['product', 'warehouse'])]

    def __str__(self):
        unit_str = self.product.unit_display_name or ""
        return f"{self.product.name} in {self.warehouse.name}: {self.quantity} {unit_str}".strip()

# --- Order Model ---
class Order(BaseModel):
    class OrderStatus(models.TextChoices):
        PENDING = 'pending', 'Pending Payment'
        AWAITING_PROCESSING = 'awaiting_processing', 'Awaiting Processing'
        PROCESSING = 'processing', 'Processing'
        SHIPPED = 'shipped', 'Shipped'
        DELIVERED = 'delivered', 'Delivered'
        COMPLETED = 'completed', 'Completed'
        CANCELLED = 'cancelled', 'Cancelled'
        REFUNDED = 'refunded', 'Refunded'
        PARTIALLY_SHIPPED = 'partially_shipped', 'Partially Shipped'

    order_number = models.CharField(max_length=50, unique=True, db_index=True, help_text="Unique order identifier")
    contragent = models.ForeignKey(
        Contragent,
        on_delete=models.PROTECT,
        related_name='sales_orders',
        limit_choices_to={'contragent_type__in': [Contragent.ContragentType.CUSTOMER, Contragent.ContragentType.PARTNER]}
    )
    status = models.CharField(max_length=25, choices=OrderStatus.choices, default=OrderStatus.PENDING, db_index=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='USD')
    
    shipping_address_snapshot = models.TextField(blank=True, null=True, help_text="Snapshot of shipping address at time of order")
    billing_address_snapshot = models.TextField(blank=True, null=True, help_text="Snapshot of billing address at time of order")
    
    notes = models.TextField(blank=True, null=True, help_text="Internal notes or customer requests")
    paid_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey( # Who created the order in the system
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_orders'
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_number']),
            models.Index(fields=['contragent', 'status']),
        ]

    def save(self, *args, **kwargs):
        if not self.order_number:
            timestamp_part = timezone.now().strftime('%y%m%d%H%M')
            uuid_part = str(self.id).split('-')[0].upper()
            self.order_number = f"ORD-{timestamp_part}-{uuid_part}"
        
        # Snapshot addresses from contragent if not provided
        if not self.shipping_address_snapshot and self.contragent_id:
            self.shipping_address_snapshot = self.contragent.address_shipping
        if not self.billing_address_snapshot and self.contragent_id:
            self.billing_address_snapshot = self.contragent.address_billing
            
        super().save(*args, **kwargs)
        
    def update_total_amount(self):
        total = self.items.aggregate(
            total_sum=models.Sum(models.F('quantity') * models.F('unit_price'))
        )['total_sum'] or Decimal('0.00')
        if self.total_amount != total:
            self.total_amount = total
            self.save(update_fields=['total_amount', 'modified_at'])

    def __str__(self):
        return f"Order {self.order_number} for {self.contragent.name if self.contragent else 'N/A'}"

# --- OrderItem Model ---
class OrderItem(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='order_items')
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Price per unit at the time of sale")
    
    @property
    def total_price(self):
        return self.quantity * self.unit_price

    class Meta(BaseModel.Meta):
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        ordering = ['order', 'product__name']

    def __str__(self):
        unit_str = self.product.unit_display_name or ""
        return f"{self.quantity} {unit_str} of {self.product.name} in Order {self.order.order_number}".strip()

# --- StockMovement Model ---
class StockMovement(BaseModel):
    class MovementType(models.TextChoices):
        SALE = 'sale', 'Sale'
        PURCHASE_RECEIPT = 'purchase_receipt', 'Purchase Receipt'
        CUSTOMER_RETURN = 'customer_return', 'Customer Return'
        SUPPLIER_RETURN = 'supplier_return', 'Return to Supplier'
        ADJUSTMENT_IN = 'adjustment_in', 'Adjustment (Increase)'
        ADJUSTMENT_OUT = 'adjustment_out', 'Adjustment (Decrease)'
        TRANSFER_OUT = 'transfer_out', 'Transfer Out'
        TRANSFER_IN = 'transfer_in', 'Transfer In'
        INITIAL_STOCK = 'initial_stock', 'Initial Stock'
        PRODUCTION_IN = 'production_in', 'Production Output'
        PRODUCTION_OUT = 'production_out', 'Component Consumption'


    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='stock_movements')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='stock_movements')
    quantity_changed = models.DecimalField(max_digits=10, decimal_places=2, help_text="Positive for increase, negative for decrease")
    movement_type = models.CharField(max_length=25, choices=MovementType.choices, db_index=True)
    reason = models.CharField(max_length=255, blank=True, null=True)
    
    order_item = models.ForeignKey(OrderItem, on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_movements')
    purchase_order_item = models.ForeignKey('PurchaseOrderItem', on_delete=models.SET_NULL, null=True, blank=True, related_name='stock_movements')
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        help_text="User who performed/recorded the movement"
    )
    document_ref = models.CharField(max_length=100, blank=True, null=True, help_text="Reference to a source document (e.g., invoice, act)")


    class Meta(BaseModel.Meta):
        verbose_name = "Stock Movement"
        verbose_name_plural = "Stock Movements"
        ordering = ['-created_at', 'product__name']
        indexes = [
            models.Index(fields=['product', 'warehouse', 'movement_type']),
            models.Index(fields=['movement_type']),
        ]

    def __str__(self):
        direction = "IN" if self.quantity_changed > 0 else "OUT"
        unit_str = self.product.unit_display_name or ""
        return f"{self.get_movement_type_display()}: {abs(self.quantity_changed)} {unit_str} of {self.product.name} ({direction}) at {self.warehouse.name}".strip()

# --- PurchaseOrder Model ---
class PurchaseOrder(BaseModel):
    class POStatus(models.TextChoices):
        DRAFT = 'draft', 'Draft'
        SUBMITTED = 'submitted', 'Submitted'
        ACKNOWLEDGED = 'acknowledged', 'Acknowledged by Supplier'
        PARTIALLY_RECEIVED = 'partially_received', 'Partially Received'
        FULLY_RECEIVED = 'fully_received', 'Fully Received'
        CANCELLED = 'cancelled', 'Cancelled'
        CLOSED = 'closed', 'Closed' # After full receipt & payment or cancellation

    po_number = models.CharField(max_length=50, unique=True, db_index=True, help_text="Unique purchase order identifier")
    contragent = models.ForeignKey(
        Contragent,
        on_delete=models.PROTECT,
        related_name='purchase_orders_placed_with',
        limit_choices_to={'contragent_type__in': [Contragent.ContragentType.SUPPLIER, Contragent.ContragentType.PARTNER]}
    )
    status = models.CharField(max_length=25, choices=POStatus.choices, default=POStatus.DRAFT, db_index=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    actual_delivery_date = models.DateField(null=True, blank=True)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=3, default='USD')
    notes = models.TextField(blank=True, null=True)
    destination_warehouse = models.ForeignKey(
        Warehouse, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        help_text="Warehouse where items will be received"
    )
    created_by = models.ForeignKey( # Who created the PO in the system
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_purchase_orders'
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Purchase Order"
        verbose_name_plural = "Purchase Orders"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['po_number']),
            models.Index(fields=['contragent', 'status']),
        ]

    def save(self, *args, **kwargs):
        if not self.po_number:
            timestamp_part = timezone.now().strftime('%y%m%d%H%M')
            uuid_part = str(self.id).split('-')[0].upper()
            self.po_number = f"PO-{timestamp_part}-{uuid_part}"
        super().save(*args, **kwargs)

    def update_total_cost(self):
        total = self.items.aggregate(
            total_sum=models.Sum(models.F('quantity_ordered') * models.F('unit_cost'))
        )['total_sum'] or Decimal('0.00')
        if self.total_cost != total:
            self.total_cost = total
            self.save(update_fields=['total_cost', 'modified_at'])

    def __str__(self):
        return f"Purchase Order {self.po_number} to {self.contragent.name if self.contragent else 'N/A'}"

# --- PurchaseOrderItem Model ---
class PurchaseOrderItem(BaseModel):
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='purchase_order_items')
    quantity_ordered = models.DecimalField(max_digits=10, decimal_places=2)
    quantity_received = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, help_text="Cost per unit from supplier")
    
    @property
    def total_cost(self):
        return self.quantity_ordered * self.unit_cost

    class Meta(BaseModel.Meta):
        verbose_name = "Purchase Order Item"
        verbose_name_plural = "Purchase Order Items"
        unique_together = [['purchase_order', 'product']]
        ordering = ['purchase_order', 'product__name']

    def __str__(self):
        unit_str = self.product.unit_display_name or ""
        return f"{self.quantity_ordered} {unit_str} of {self.product.name} in PO {self.purchase_order.po_number}".strip()

# --- Payment Model ---
class Payment(BaseModel):
    class PaymentMethod(models.TextChoices):
        CREDIT_CARD = 'credit_card', 'Credit Card'
        BANK_TRANSFER = 'bank_transfer', 'Bank Transfer'
        CASH = 'cash', 'Cash'
        PAYPAL = 'paypal', 'PayPal'
        INTERNAL_ACCOUNT = 'internal_account', 'Internal Account'
        OTHER = 'other', 'Other'

    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'
        PARTIALLY_REFUNDED = 'partially_refunded', 'Partially Refunded'

    order = models.ForeignKey(Order, on_delete=models.SET_NULL, related_name='payments', null=True, blank=True)
    purchase_order = models.ForeignKey(PurchaseOrder, on_delete=models.SET_NULL, related_name='payments', null=True, blank=True)
    contragent = models.ForeignKey(Contragent, on_delete=models.SET_NULL, related_name='payments', null=True, blank=True, help_text="Payer or Payee if not linked to Order/PO")

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    transaction_id = models.CharField(max_length=255, blank=True, null=True, db_index=True, help_text="ID from payment gateway or bank")
    payment_date = models.DateTimeField(default=timezone.now, help_text="Actual date of payment transaction")
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_payments'
    )

    class Meta(BaseModel.Meta):
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        ordering = ['-payment_date']

    def __str__(self):
        target = ""
        if self.order:
            target = f"Order {self.order.order_number}"
        elif self.purchase_order:
            target = f"PO {self.purchase_order.po_number}"
        elif self.contragent:
            target = f"Contragent {self.contragent.name}"
        else:
            target = "Ad-hoc Payment"
        
        return f"Payment {self.transaction_id or self.id} ({self.amount} {self.currency}) for {target}"