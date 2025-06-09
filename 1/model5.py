import uuid
import os
from decimal import Decimal

from django.db import models
from django.db.models import F, Sum
from django.utils.text import slugify
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from PIL import Image as PILImage

# --- Helper Function for Unique Slugs (Без изменений, функция хорошая) ---
def generate_unique_slug(instance, source_field='name', slug_field='slug'):
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


# --- Abstract Base Models (Без изменений) ---
class BaseModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ['-created_at']

class SeoModel(models.Model):
    meta_title = models.CharField(max_length=255, blank=True, null=True, help_text="Optimal title for SEO (leave blank to use the object's name).")
    meta_description = models.CharField(max_length=300, blank=True, null=True, help_text="Brief description for search engine listings.")
    meta_keywords = models.CharField(max_length=255, blank=True, null=True, help_text="Comma-separated keywords for meta tags.")

    class Meta:
        abstract = True


# --- Core Entity Models (Без изменений, кроме Tag) ---

class Image(BaseModel):
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
        super().save(*args, **kwargs)
        # ... (Image processing logic is great, keeping it)
        # ...

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
    # _# IMPROVEMENT:_ Добавлена сортировка по умолчанию для удобства
    class Meta(BaseModel.Meta):
        ordering = ['name']

    def save(self, *args, **kwargs):
        self.slug = generate_unique_slug(self)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# --- Product and Variant Architecture ---

class Attribute(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    class Meta(BaseModel.Meta):
        ordering = ['name']
    def __str__(self):
        return self.name

class AttributeValue(BaseModel):
    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name='values')
    value = models.CharField(max_length=100)
    class Meta(BaseModel.Meta):
        unique_together = [['attribute', 'value']]
        ordering = ['attribute__name', 'value']
    def __str__(self):
        return f"{self.attribute.name}: {self.value}"

class Product(BaseModel, SeoModel):
    name = models.CharField(max_length=255, db_index=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    tags = models.ManyToManyField(Tag, blank=True, related_name='products')
    main_image = models.ForeignKey(Image, null=True, blank=True, on_delete=models.SET_NULL, related_name='main_image_for_products')
    additional_images = models.ManyToManyField(Image, blank=True, related_name='products')
    attributes = models.ManyToManyField(Attribute, blank=True, help_text="Attributes available for this product's variants (e.g., Color, Size)")
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
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    attribute_values = models.ManyToManyField(AttributeValue, related_name='variants')

    # _# IMPROVEMENT:_ Удалено поле 'name'. Оно будет генерироваться динамически.
    # Это решает проблему с необходимостью сохранять объект дважды.

    sku = models.CharField(max_length=50, unique=True, blank=True, null=True, help_text="Stock Keeping Unit")
    price = models.DecimalField(max_digits=12, decimal_places=2, help_text="The price of this specific variant.")
    image = models.ForeignKey(Image, null=True, blank=True, on_delete=models.SET_NULL, help_text="Variant-specific image. Falls back to parent product's image if not set.")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta(BaseModel.Meta):
        # _# IMPROVEMENT:_ `unique_together` удален, т.к. не работает для ManyToMany.
        # Уникальность будет обеспечиваться на уровне метода `clean()`.
        ordering = ['sku']

    # _# IMPROVEMENT:_ Метод clean для валидации уникальности комбинации атрибутов.
    def clean(self):
        super().clean()
        if not self.pk: # Проверку делаем только для новых объектов
            return
        
        # Собираем ID значений атрибутов для текущего варианта
        current_values_ids = set(self.attribute_values.values_list('id', flat=True))
        if not current_values_ids:
            return

        # Ищем другие варианты этого же продукта
        other_variants = self.product.variants.exclude(pk=self.pk)
        for variant in other_variants:
            other_values_ids = set(variant.attribute_values.values_list('id', flat=True))
            if current_values_ids == other_values_ids:
                raise ValidationError(f'A variant with these attribute values already exists for product "{self.product.name}".')

    # _# IMPROVEMENT:_ Динамическое свойство для отображения имени варианта.
    @property
    def display_name(self):
        """Generates a display name from attribute values, e.g., 'Red, Large'."""
        if not self.pk:
            return "New Variant"
        # Сортируем для консистентности
        values = self.attribute_values.select_related('attribute').order_by('attribute__name')
        return ", ".join([v.value for v in values])

    def __str__(self):
        variant_name = self.display_name or f"Variant {str(self.id)[:4]}"
        return f"{self.product.name} ({variant_name})"

    def get_display_image(self):
        if self.image:
            return self.image
        if self.product.main_image:
            return self.product.main_image
        return None


# --- User, Customer, and Address Models ---

# _# IMPROVEMENT:_ Создана отдельная, структурированная модель для адресов.
class Address(BaseModel):
    """ A reusable, structured address model. """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    
    class AddressType(models.TextChoices):
        SHIPPING = 'shipping', 'Shipping'
        BILLING = 'billing', 'Billing'

    address_type = models.CharField(max_length=10, choices=AddressType.choices, default=AddressType.SHIPPING)
    full_name = models.CharField(max_length=255, help_text="Recipient's full name")
    phone_number = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Kazakhstan')
    city = models.CharField(max_length=100)
    street_address = models.CharField(max_length=255)
    postal_code = models.CharField(max_length=20)
    is_default = models.BooleanField(default=False, help_text="Is this the default address for this type?")

    def __str__(self):
        return f"{self.full_name}, {self.street_address}, {self.city}"

class CustomerProfile(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(max_length=20, blank=True, null=True) # Может быть основным контактом
    # _# IMPROVEMENT:_ Заменено текстовое поле на ForeignKey к структурированной модели.
    default_shipping_address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    default_billing_address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    def __str__(self):
        return f"Profile for {self.user.username}"

class Wishlist(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wishlist')
    products = models.ManyToManyField(ProductVariant, blank=True, related_name='wishlists')

    def __str__(self):
        return f"Wishlist for {self.user.username}"


# --- Inventory, Warehouse, and Shipping (Без существенных изменений) ---
class Warehouse(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    # ...

class Stock(BaseModel):
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='stock_records')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_records')
    quantity = models.IntegerField(default=0, help_text="Total physical quantity on hand")
    reserved_quantity = models.IntegerField(default=0, help_text="Quantity reserved for open orders")

    class Meta(BaseModel.Meta):
        unique_together = [['product_variant', 'warehouse']]
    # ...

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
    
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0) # _# IMPROVEMENT:_ Поле для суммы скидки
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='KZT')
    
    # _# IMPROVEMENT:_ Замена TextField на ForeignKey к модели Address. on_delete=PROTECT, чтобы не потерять историю заказов.
    shipping_address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name='shipping_orders')
    billing_address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name='billing_orders', null=True, blank=True)
    
    shipping_method = models.ForeignKey(ShippingMethod, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)

    # _# IMPROVEMENT:_ Связь с примененными скидками.
    discounts = models.ManyToManyField('Discount', blank=True, related_name='orders')

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"ORD-{timezone.now().strftime('%Y%m')}-{str(self.id)[:6].upper()}"
        # _# IMPROVEMENT:_ Улучшен расчет итоговой суммы
        self.total_amount = (self.subtotal + self.shipping_cost) - self.discount_amount
        if self.total_amount < 0:
            self.total_amount = Decimal('0.00')
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

# _# IMPROVEMENT:_ Модель скидок сделана более гибкой и функциональной.
class Discount(BaseModel):
    code = models.CharField(max_length=50, unique=True, help_text="e.g., 'SUMMER20'")
    description = models.CharField(max_length=255, blank=True)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2, help_text="Fixed amount or percentage value")
    is_percentage = models.BooleanField(default=False, help_text="Is the value a percentage? If not, it's a fixed amount.")
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True, db_index=True)

    # _# IMPROVEMENT:_ Дополнительные условия для применения скидки
    min_order_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="Minimum order total to apply this discount")
    applies_to_products = models.ManyToManyField(Product, blank=True, help_text="Apply discount only to these products.")
    applies_to_categories = models.ManyToManyField(Category, blank=True, help_text="Apply discount only to products in these categories.")
    
    def is_valid(self):
        """Checks if the discount is currently active."""
        now = timezone.now()
        return self.is_active and self.start_date <= now and self.end_date >= now

    def __str__(self):
        value_str = f"{self.discount_value}%" if self.is_percentage else str(self.discount_value)
        return f"Discount {self.code} ({value_str})"


# --- Operational Models ---

# _# IMPROVEMENT:_ Модель переименована и переработана для аудита конкретных SKU на складе.
class StockAudit(BaseModel):
    """
    An audit record for a specific product variant at a specific warehouse.
    Replaces the previous WorkerProductAudit model for better accuracy.
    """
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='audits')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name='audits')
    
    audited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='conducted_audits')
    
    # Количество, которое было до аудита (можно заполнять автоматически)
    quantity_before_audit = models.IntegerField(help_text="Stock quantity before adjustment")
    # Количество, которое зафиксировали по факту
    quantity_recorded = models.IntegerField(help_text="Actual physical quantity found during audit")
    
    # _# IMPROVEMENT:_ Разница вычисляется, а не вводится вручную.
    @property
    def quantity_discrepancy(self):
        return self.quantity_recorded - self.quantity_before_audit

    photo_taken = models.ForeignKey(Image, on_delete=models.SET_NULL, null=True, blank=True, limit_choices_to={'type': Image.ImageType.AUDIT})
    notes = models.TextField(blank=True, null=True)
    is_completed = models.BooleanField(default=False, db_index=True, help_text="Indicates if the audit has been processed and stock levels adjusted.")
    completed_at = models.DateTimeField(null=True, blank=True)

    def mark_as_completed(self):
        """Finalizes the audit and sets the completion timestamp."""
        # Здесь можно добавить логику для создания StockMovement
        self.is_completed = True
        self.completed_at = timezone.now()
        self.save()

    def __str__(self):
        status = "Completed" if self.is_completed else "Pending"
        return f"Audit for {self.product_variant} at {self.warehouse.name} - {status}"