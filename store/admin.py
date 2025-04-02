from django.contrib import admin
from .models import Image, Category, Tag, Price, Product

@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = ('file_path', 'resolution', 'size', 'format', 'created_at')
    list_filter = ('format', 'created_at')
    search_fields = ('description', 'alt_text')
    readonly_fields = ('resolution', 'size', 'format')

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'parent', 'created_at')
    list_filter = ('parent', 'created_at')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at')
    search_fields = ('name',)
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    list_display = ('product', 'amount', 'currency', 'is_active', 'created_at')
    list_filter = ('currency', 'is_active', 'created_at')
    search_fields = ('product__name', 'description')
    raw_id_fields = ('product',)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'is_active', 'is_featured', 'created_at')
    list_filter = ('category', 'is_active', 'is_featured', 'created_at')
    search_fields = ('name', 'description', 'short_description')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('tags', 'images')
    raw_id_fields = ('category',)
