import uuid
from django.db import models
from django.utils.text import slugify
from django.utils import timezone
from PIL import Image as PILImage
import os
from decimal import Decimal
from django.contrib.auth.models import User

# --- Helper Function for Unique Slugs ---
def generate_unique_slug(instance, source_field='name', slug_field='slug'):
    """
    Generates a unique slug for the instance.
    Appends '-<number>' if the initial slug already exists.
    """
    if getattr(instance, slug_field) and not instance._state.adding:
        # Do not regenerate slug if it already exists and we are updating
        return getattr(instance, slug_field)

    base_slug = slugify(getattr(instance, source_field))
    if not base_slug: # Handle cases where source_field might be empty
        base_slug = str(instance.id)[:8] # Use part of UUID if name is empty

    slug = base_slug
    num = 1
    ModelClass = instance.__class__

    # Check for uniqueness excluding the current instance if it's already saved
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
        AUDIT = 'audit', 'Audit Photo'
    
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
        help_text="Type of the image (e.g., category photo, product photo, barcode, etc.)",
        db_index=True
    )
    is_main = models.BooleanField(
        default=False, 
        db_index=True,
        help_text="Mark this image as the main image for the product"
    )

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        
        # If this image is being set as main, unset any other main images for the same products
        if self.is_main:
            # We need to save first to ensure M2M relationships exist
            super().save(*args, **kwargs)
            
            # For each product this image is associated with, unset other main images
            for product in self.products.all():
                # Exclude current image and update all others
                product.images.exclude(pk=self.pk).filter(is_main=True).update(is_main=False)
                
            # Return early since we already called super().save()
            return
        else:
            # Proceed with normal save if not setting as main
            super().save(*args, **kwargs)

        if (is_new or 'file_path' in kwargs.get('update_fields', [])) and self.file_path:
            try:
                img_path = self.file_path.path
                img = PILImage.open(img_path)

                # --- Optional: Image Optimization ---
                max_size = (1920, 1080) # Example max dimensions
                img_changed = False
                current_format = img.format

                if img.width > max_size[0] or img.height > max_size[1]:
                    img.thumbnail(max_size, PILImage.Resampling.LANCZOS)
                    img_changed = True

                if img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                    img_changed = True

                save_kwargs = {'quality': 85, 'optimize': True}
                save_format = current_format if current_format in ['JPEG', 'PNG', 'GIF'] else 'JPEG'
                if img_changed:
                    img.save(img_path, format=save_format, **save_kwargs)

                # --- Update Metadata ---
                with PILImage.open(img_path) as final_img:
                    res = f"{final_img.width}x{final_img.height}"
                    fmt = final_img.format
                    sz = os.path.getsize(img_path) // 1024 # Size in KB

                # Update fields without recursion if they changed
                if self.resolution != res or self.format != fmt or self.size != sz:
                    Image.objects.filter(pk=self.pk).update(resolution=res, size=sz, format=fmt)

            except FileNotFoundError:
                print(f"Warning: Could not process image {getattr(self.file_path, 'path', 'N/A')}, file not found.")
            except Exception as e:
                print(f"Error processing image {getattr(self.file_path, 'path', 'N/A')}: {e}")

    def __str__(self):
        if self.file_path:
            base_name = os.path.basename(self.file_path.name)
            return f"{base_name} ({self.format})" if self.format else base_name
        return f"Image {self.id}"

# --- Category Model ---
class Category(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    name_2 = models.CharField(max_length=255, blank=True, null=True)
    category_article = models.CharField(max_length=50, blank=True, null=True, help_text="Category article/reference code", db_index=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    parent = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='children', db_index=True)
    image = models.ForeignKey(Image, null=True, blank=True, on_delete=models.SET_NULL, related_name='category_images')

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

# --- Price Model ---
class Price(BaseModel):
    class PriceType(models.TextChoices):
        SELLING = 'selling', 'Selling Price'
        PURCHASE = 'purchase', 'Purchase Price'
        REGULAR = 'regular', 'Regular Price'
        DISCOUNT = 'discount', 'Discount Price'
        WHOLESALE = 'wholesale', 'Wholesale Price'
        OTHER = 'other', 'Other Price'

    class Currency(models.TextChoices):
        KZT = 'KZT', 'Казахстанский тенге'        
        USD = 'USD', 'Доллар США'
        EUR = 'EUR', 'Евро'
        RUB = 'RUB', 'Российский рубль' 
        OTHER = 'OTHER', 'Other Currency'   

    product = models.ForeignKey('Product', on_delete=models.CASCADE, related_name='prices')
    price_type = models.CharField(
        max_length=20,
        choices=PriceType.choices,
        default=PriceType.REGULAR,
        db_index=True,
        help_text="Type of the price (e.g., selling, purchase, discount)"
    )
    currency = models.CharField(
        max_length=10,
        choices=Currency.choices,
        default=Currency.KZT,
        db_index=True,
        help_text="Currency of the price"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.CharField(max_length=100, blank=True, null=True, help_text="Optional: further details about this price")
    is_active = models.BooleanField(default=True, help_text="Is this price currently active?")

    class Meta(BaseModel.Meta):
        ordering = ['product', '-is_active', 'price_type', 'amount']
        unique_together = [['product', 'price_type', 'currency']] # A product should have one unique price per type and currency
        indexes = [
            models.Index(fields=['product', 'price_type', 'is_active']),
        ]

    def __str__(self):
        type_display = self.get_price_type_display()
        desc = f" ({self.description})" if self.description else ""
        active_status = "" if self.is_active else " (Inactive)"
        return f"{self.product.name}: {self.amount} {self.currency} ({type_display}){desc}{active_status}"

# --- Product Model ---
class Product(BaseModel):
    name = models.CharField(max_length=255, db_index=True)
    name_2 = models.CharField(max_length=255, blank=True, null=True)
    article_number = models.CharField(max_length=50, blank=True, null=True, help_text="Product article/SKU number", db_index=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    short_description = models.CharField(max_length=255, blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, db_index=True, related_name='products')
    tags = models.ManyToManyField(Tag, blank=True, related_name='products')
    images = models.ManyToManyField(Image, blank=True, related_name='products')
    is_featured = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True, help_text="Is this product visible on the site?")

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['is_active', 'is_featured']),
            models.Index(fields=['name']),
            models.Index(fields=['category']),
        ]
        ordering = ['name']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(self, 'name', 'slug')
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    @property
    def current_price_display(self):
        """Returns the first active price found, or None."""
        active_price = self.prices.filter(is_active=True).order_by('amount').first()
        if active_price:
            return f"{active_price.amount} {active_price.currency}"
        return "Price not available"

    @property
    def main_image(self):
        """Returns the main image of the product, or the first image if no main image is set, or None."""
        main_image = self.images.filter(is_main=True).first()
        if main_image:
            return main_image
        # Fall back to the first image if no main image is set
        return self.images.first()

# --- Worker Product Audit Model ---
class WorkerProductAudit(BaseModel):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='worker_audit_details')
    last_audited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audited_products')
    quantity_recorded = models.PositiveIntegerField(null=True, blank=True)
    photo_taken = models.ForeignKey(
        Image, 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='audit_photos',
        limit_choices_to={'type': Image.ImageType.AUDIT} # Ensure only audit images can be linked
    )
    is_completed = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        ordering = ['product__name']
        verbose_name = "Worker Product Audit"
        verbose_name_plural = "Worker Product Audits"

    def save(self, *args, **kwargs):
        if self.quantity_recorded is not None and self.photo_taken is not None:
            if not self.is_completed: # Only update completed_at if it's newly completed
                self.is_completed = True
                self.completed_at = timezone.now()
        else:
            # If either is None, or if it was completed but now isn't (e.g. photo removed)
            if self.is_completed: 
                self.is_completed = False
                self.completed_at = None
        super().save(*args, **kwargs)

    def __str__(self):
        status = "Completed" if self.is_completed else "Pending"
        worker_name = self.last_audited_by.username if self.last_audited_by else "N/A"
        return f"Audit for {self.product.name} by {worker_name} - {status}"

# --- Warehouse Model ---
class Warehouse(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    address = models.TextField(blank=True, null=True, help_text="Physical address of the warehouse")
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True, help_text="Is this warehouse currently active?")
    image = models.ForeignKey(
        Image,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='warehouses',
        help_text="Main image for the warehouse"
    )

    class Meta(BaseModel.Meta):
        verbose_name_plural = "Warehouses"
        indexes = [models.Index(fields=['slug']), models.Index(fields=['is_active'])]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(self, 'name', 'slug')
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"

# --- Stock Model ---
class Stock(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stocks')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stocks')
    quantity = models.PositiveIntegerField(default=0, help_text="Available quantity in stock")
    reserved_quantity = models.PositiveIntegerField(default=0, help_text="Quantity reserved for orders")
    minimum_stock_level = models.PositiveIntegerField(default=0, help_text="Minimum stock level for alerts")
    last_updated = models.DateTimeField(auto_now=True, db_index=True)

    class Meta(BaseModel.Meta):
        unique_together = [['product', 'warehouse']]
        indexes = [
            models.Index(fields=['product', 'warehouse']),
            models.Index(fields=['last_updated']),
        ]
        ordering = ['product', 'warehouse']

    def __str__(self):
        return f"{self.product.name} at {self.warehouse.name}: {self.quantity} units"

    @property
    def available_quantity(self):
        """Returns the quantity available after accounting for reservations."""
        return self.quantity - self.reserved_quantity

# --- Counterparty Model ---
class Counterparty(BaseModel):
    class CounterpartyType(models.TextChoices):
        SUPPLIER = 'supplier', 'Supplier'
        BUYER = 'buyer', 'Buyer'
        WORKER = 'worker', 'Worker'
        CUSTOMER = 'customer', 'Customer'
        OTHER = 'other', 'Other'

    name = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    counterparty_type = models.CharField(
        max_length=20,
        choices=CounterpartyType.choices,
        help_text="Type of counterparty (e.g., supplier, buyer, worker)",
        db_index=True
    )
    email = models.EmailField(blank=True, null=True, help_text="Contact email")
    phone = models.CharField(max_length=20, blank=True, null=True, help_text="Contact phone number")
    address = models.TextField(blank=True, null=True, help_text="Physical or mailing address")
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True, help_text="Is this counterparty active?")
    image = models.ForeignKey(
        Image,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='counterparties',
        help_text="Main image or logo for the counterparty"
    )

    class Meta(BaseModel.Meta):
        indexes = [
            models.Index(fields=['slug']),
            models.Index(fields=['counterparty_type', 'is_active']),
        ]
        ordering = ['name', 'counterparty_type']

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_unique_slug(self, 'name', 'slug')
        super().save(*args, **kwargs)

    def __str__(self):
        type_display = self.get_counterparty_type_display()
        return f"{self.name} ({type_display})"
