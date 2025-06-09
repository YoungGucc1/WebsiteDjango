import uuid
import os
from decimal import Decimal

from django.db import models, transaction
from django.db.models import F, Sum, Q, Count
from django.utils.text import slugify
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.core.exceptions import ValidationError
from PIL import Image as PILImage

# --- Helper Function for Unique Slugs (Без изменений) ---
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
    meta_title = models.CharField(max_length=255, blank=True, null=True)
    meta_description = models.CharField(max_length=300, blank=True, null=True)
    meta_keywords = models.CharField(max_length=255, blank=True, null=True)
    class Meta:
        abstract = True

# --- Core Entity Models (Без изменений) ---
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
    class Meta(BaseModel.Meta): ordering = ['name']
    def __str__(self): return self.name

class AttributeValue(BaseModel):
    attribute = models.ForeignKey(Attribute, on_delete=models.CASCADE, related_name='values')
    value = models.CharField(max_length=100)
    class Meta(BaseModel.Meta):
        unique_together = [['attribute', 'value']]
        ordering = ['attribute__name', 'value']
    def __str__(self): return f"{self.attribute.name}: {self.value}"

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
    def __str__(self): return self.name

# _# IMPROVEMENT:_ Добавлен кастомный менеджер для массовых операций
class ProductVariantManager(models.Manager):
    def bulk_set_price(self, variant_ids, value, is_percentage=False):
        """
        Массово обновляет цены для указанных вариантов.
        - value: Новая цена или процент (например, 10 для +10% или -15 для -15%).
        - is_percentage: True, если value - это процент.
        """
        variants = self.filter(pk__in=variant_ids)
        if is_percentage:
            multiplier = Decimal(1) + (Decimal(value) / Decimal(100))
            return variants.update(price=F('price') * multiplier)
        else:
            return variants.update(price=Decimal(value))

class ProductVariant(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    attribute_values = models.ManyToManyField(AttributeValue, related_name='variants')
    sku = models.CharField(max_length=50, unique=True, blank=True, null=True, help_text="Stock Keeping Unit")
    price = models.DecimalField(max_digits=12, decimal_places=2)
    image = models.ForeignKey(Image, null=True, blank=True, on_delete=models.SET_NULL)
    is_active = models.BooleanField(default=True, db_index=True)
    
    # _# IMPROVEMENT:_ Подключаем кастомный менеджер
    objects = ProductVariantManager()
    
    class Meta(BaseModel.Meta):
        ordering = ['sku']
    
    def clean(self):
        """
        Проверяет, что не существует другого варианта с точно такой же комбинацией значений атрибутов.
        Внимание: Эта проверка наиболее надежна на уровне бизнес-логики (сериализаторы, сервисы),
        так как m2m-связи сохраняются после основного объекта.
        """
        super().clean()
        if not self.pk or not self.product_id:
            return
        
        value_ids = set(self.attribute_values.values_list('pk', flat=True))
        if not value_ids:
            return
        
        # Ищем другие варианты этого же продукта
        conflicting_variants = ProductVariant.objects.filter(product=self.product).exclude(pk=self.pk)
        # У которых такое же количество атрибутов
        conflicting_variants = conflicting_variants.annotate(num_values=Count('attribute_values')).filter(num_values=len(value_ids))
        # И все атрибуты совпадают
        for value_id in value_ids:
            conflicting_variants = conflicting_variants.filter(attribute_values__pk=value_id)
        
        if conflicting_variants.exists():
            raise ValidationError(f'A variant with these attribute values already exists for product "{self.product.name}".')

    def save(self, *args, **kwargs):
        # self.full_clean() здесь не всегда сработает для m2m при создании.
        # Валидацию лучше проводить на уровне форм/сериализаторов.
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        if not self.pk: return "New Variant"
        values = self.attribute_values.select_related('attribute').order_by('attribute__name')
        return ", ".join([v.value for v in values])

    def __str__(self):
        return f"{self.product.name} ({self.display_name or f'Variant {str(self.id)[:4]}'})"

    def get_display_image(self):
        return self.image or self.product.main_image

# --- User, Customer, and Address Models ---
class Address(BaseModel):
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
    is_default = models.BooleanField(default=False, help_text="Is this the default address for this type?")

    # _# IMPROVEMENT:_ Атомарное управление адресом по умолчанию
    def save(self, *args, **kwargs):
        if self.is_default:
            # Сбросить флаг is_default у всех других адресов этого пользователя и этого типа
            Address.objects.filter(
                user=self.user, 
                address_type=self.address_type
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name}, {self.street_address}, {self.city}"

class CustomerProfile(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    default_shipping_address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    default_billing_address = models.ForeignKey(Address, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    def __str__(self): return f"Profile for {self.user.username}"

class Wishlist(BaseModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wishlist')
    products = models.ManyToManyField(ProductVariant, blank=True, related_name='wishlists')
    def __str__(self): return f"Wishlist for {self.user.username}"

# --- Inventory, Warehouse, and Shipping ---
class Warehouse(BaseModel):
    name = models.CharField(max_length=255, unique=True)
    address = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True, db_index=True)
    def __str__(self): return self.name

class Stock(BaseModel):
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='stock_records')
    warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name='stock_records')
    quantity = models.IntegerField(default=0, help_text="Total physical quantity on hand")
    reserved_quantity = models.IntegerField(default=0, help_text="Quantity reserved for open orders")
    class Meta(BaseModel.Meta):
        unique_together = [['product_variant', 'warehouse']]
    @property
    def available_quantity(self):
        return self.quantity - self.reserved_quantity

class StockMovement(BaseModel):
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
    related_audit = models.ForeignKey('StockAudit', on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(blank=True, null=True)
    def __str__(self):
        return f"{self.movement_type}: {self.quantity_changed} x {self.product_variant} at {self.warehouse.name}"

class ShippingMethod(BaseModel):
    name = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='KZT')
    is_active = models.BooleanField(default=True)
    def __str__(self): return f"{self.name} ({self.price} {self.currency})"

# --- Cart, Order, and Payment Models ---
class Cart(BaseModel):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE, related_name='carts')
    session_key = models.CharField(max_length=40, null=True, blank=True, db_index=True)
    def __str__(self):
        if self.user: return f"Cart for {self.user.username}"
        return f"Anonymous Cart (Session: {self.session_key})"
    @property
    def subtotal(self):
        return self.items.aggregate(subtotal=Sum(F('quantity') * F('product_variant__price')))['subtotal'] or Decimal('0.00')

class CartItem(BaseModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.CASCADE, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1)
    class Meta(BaseModel.Meta): unique_together = [['cart', 'product_variant']]
    @property
    def total_price(self): return self.quantity * self.product_variant.price
    def __str__(self): return f"{self.quantity} x {self.product_variant} in {self.cart}"

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
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='KZT')
    shipping_address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name='shipping_orders')
    billing_address = models.ForeignKey(Address, on_delete=models.PROTECT, related_name='billing_orders', null=True, blank=True)
    shipping_method = models.ForeignKey(ShippingMethod, on_delete=models.SET_NULL, null=True, blank=True)
    discounts = models.ManyToManyField('Discount', blank=True, related_name='orders')
    notes = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"ORD-{timezone.now().strftime('%Y%m')}-{str(self.id)[:6].upper()}"
        self.total_amount = max(Decimal('0.00'), (self.subtotal + self.shipping_cost) - self.discount_amount)
        super().save(*args, **kwargs)
    def __str__(self): return f"Order {self.order_number} ({self.status})"

class OrderItem(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product_variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='order_items')
    quantity = models.PositiveIntegerField(default=1)
    price_per_unit = models.DecimalField(max_digits=12, decimal_places=2)
    @property
    def total_price(self): return self.quantity * self.price_per_unit
    def __str__(self): return f"{self.quantity} x {self.product_variant} in Order {self.order.order_number}"

class Payment(BaseModel):
    class PaymentStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SUCCESSFUL = 'successful', 'Successful'
        FAILED = 'failed', 'Failed'
        REFUNDED = 'refunded', 'Refunded'
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True)
    payment_method = models.CharField(max_length=50)
    transaction_id = models.CharField(max_length=255, blank=True, null=True)
    def __str__(self): return f"Payment of {self.amount} for Order {self.order.order_number} ({self.status})"

# --- Marketing and Engagement Models ---
class Review(BaseModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='reviews')
    rating = models.PositiveSmallIntegerField(choices=[(i, f"{i} Stars") for i in range(1, 6)])
    comment = models.TextField()
    is_approved = models.BooleanField(default=True)
    class Meta(BaseModel.Meta): unique_together = [['product', 'user']]
    def __str__(self): return f"Review for {self.product.name} by {self.user.username}"

class DiscountManager(models.Manager):
    def get_active(self):
        now = timezone.now()
        return self.filter(is_active=True, start_date__lte=now, end_date__gte=now)
    
    def deactivate_expired(self):
        """Массово деактивирует все просроченные скидки. Идеально для cron/Celery."""
        now = timezone.now()
        expired_discounts = self.filter(end_date__lt=now, is_active=True)
        return expired_discounts.update(is_active=False)

class Discount(BaseModel):
    code = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=255, blank=True)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    is_percentage = models.BooleanField(default=False)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True, db_index=True)
    min_order_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    applies_to_products = models.ManyToManyField(Product, blank=True)
    applies_to_categories = models.ManyToManyField(Category, blank=True)
    
    objects = DiscountManager()
    
    def is_valid(self):
        now = timezone.now()
        return self.is_active and self.start_date <= now and self.end_date >= now
    
    def __str__(self):
        value_str = f"{self.discount_value}%" if self.is_percentage else str(self.discount_value)
        return f"Discount {self.code} ({value_str})"

# --- Operational Models ---
class StockAudit(BaseModel):
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

    # _# IMPROVEMENT:_ Активный метод, который корректирует сток
    @transaction.atomic
    def complete_audit(self):
        """
        Завершает аудит: корректирует остатки на складе и создает запись о движении.
        Возвращает True в случае успеха, False если что-то пошло не так.
        """
        if self.is_completed:
            return False # Аудит уже завершен

        discrepancy = self.quantity_discrepancy
        
        # Находим или создаем запись на складе
        stock, _ = Stock.objects.get_or_create(
            product_variant=self.product_variant,
            warehouse=self.warehouse
        )
        
        # Атомарно обновляем количество
        Stock.objects.filter(pk=stock.pk).update(quantity=F('quantity') + discrepancy)
        
        # Создаем запись о движении, если было расхождение
        if discrepancy != 0:
            StockMovement.objects.create(
                product_variant=self.product_variant,
                warehouse=self.warehouse,
                quantity_changed=discrepancy,
                movement_type=StockMovement.MovementType.ADJUSTMENT,
                notes=f"Stock audit {self.id}",
                related_audit=self
            )

        # Помечаем аудит как завершенный
        self.is_completed = True
        self.completed_at = timezone.now()
        self.save(update_fields=['is_completed', 'completed_at'])
        return True

    def __str__(self):
        status = "Completed" if self.is_completed else "Pending"
        return f"Audit for {self.product_variant} at {self.warehouse.name} - {status}"


# ---_# IMPROVEMENT:_ ЛОГИКА СЛИЯНИЯ АНОНИМНОЙ КОРЗИНЫ ПРИ АВТОРИЗАЦИИ ---
#
# ИНСТРУКЦИЯ ПО ИНТЕГРАЦИИ:
# 1. Создайте в вашем приложении (например, `cart` или `core`) файл `signals.py`.
# 2. Поместите приведенный ниже код в этот файл `signals.py`.
# 3. В файле `apps.py` вашего приложения добавьте метод `ready()`:
#
#    from django.apps import AppConfig
#
#    class YourAppConfig(AppConfig):
#        default_auto_field = 'django.db.models.BigAutoField'
#        name = 'your_app_name'
#
#        def ready(self):
#            import your_app_name.signals  # noqa
#
# 4. Убедитесь, что в `settings.py` в `INSTALLED_APPS` указан полный путь к конфигу:
#    'your_app_name.apps.YourAppConfig'
#

@receiver(user_logged_in)
@transaction.atomic
def merge_anonymous_cart_with_user_cart(sender, request, user, **kwargs):
    """
    При входе пользователя в систему эта функция объединяет его анонимную корзину (из сессии)
    с его существующей корзиной (если она есть).
    """
    session_key = request.session.session_key
    if not session_key:
        return

    try:
        # Находим анонимную корзину по ключу сессии
        anonymous_cart = Cart.objects.get(session_key=session_key, user__isnull=True)
    except Cart.DoesNotExist:
        return # Нет анонимной корзины для слияния

    try:
        # Находим корзину пользователя
        user_cart = Cart.objects.get(user=user)
        # --- Логика слияния ---
        # Перебираем товары из анонимной корзины
        for item in anonymous_cart.items.all():
            # Проверяем, есть ли такой же товар в корзине пользователя
            existing_item, created = CartItem.objects.get_or_create(
                cart=user_cart,
                product_variant=item.product_variant,
                defaults={'quantity': item.quantity}
            )
            if not created:
                # Если товар уже был, просто увеличиваем количество
                existing_item.quantity = F('quantity') + item.quantity
                existing_item.save(update_fields=['quantity'])
        
        # Удаляем пустую анонимную корзину
        anonymous_cart.delete()

    except Cart.DoesNotExist:
        # У пользователя не было корзины, просто "отдаем" ему анонимную
        anonymous_cart.user = user
        anonymous_cart.session_key = None
        anonymous_cart.save(update_fields=['user', 'session_key'])