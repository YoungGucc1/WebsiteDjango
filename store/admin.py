from django.contrib import admin
from django.utils.html import format_html
from .models import Image, Category, Tag, Price, Product

@admin.register(Image)
class ImageAdmin(admin.ModelAdmin):
    list_display = ('file_path', 'type', 'is_main', 'resolution', 'size', 'format', 'created_at')
    list_filter = ('format', 'type', 'is_main', 'created_at')
    search_fields = ('description', 'alt_text', 'name')
    readonly_fields = ('resolution', 'size', 'format')

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'category_article', 'image_preview', 'parent')
    list_filter = ('parent', 'created_at')
    search_fields = ('name', 'description', 'id', 'category_article')
    prepopulated_fields = {'slug': ('name',)}
    
    def image_preview(self, obj):
        if obj.image and obj.image.file_path:
            return format_html('<img src="{}" width="50" height="50" style="object-fit: cover;" />', obj.image.file_path.url)
        return format_html('<span style="color:gray;">No Image</span>')
    
    image_preview.short_description = 'Image'
    
    def uuid_display(self, obj):
        return str(obj.id)
    
    uuid_display.short_description = 'UUID'
    
    # Add image field to readonly_fields so it's displayed in the detailed view
    readonly_fields = ('image_preview', 'uuid_display')
    
    def get_readonly_fields(self, request, obj=None):
        if obj:  # If editing an existing object
            return self.readonly_fields
        return ()  # If creating a new object, no readonly fields

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
