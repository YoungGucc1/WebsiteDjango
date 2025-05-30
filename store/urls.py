from django.urls import path
from . import views

app_name = 'store'

urlpatterns = [
    path('', views.home, name='home'),
    path('products/', views.product_list, name='product_list'), # Changed from ProductListView
    path('product/<slug:slug>/', views.product_detail, name='product_detail'), # Changed from ProductDetailView and product_slug to slug
    path('products/<slug:category_slug>/', views.product_list, name='product_list_by_category'), # Added for consistency if used elsewhere, points to same view
    # Note: The original 'category/<slug:category_slug>/' and 'tag/<slug:tag_slug>/' might need adjustment
    # if they were intended for different views or if product_list handles this logic.
    # For now, I'll keep them pointing to product_list, assuming it can filter by category/tag if needed,
    # or they can be adjusted later if specific views for these exist or are created.
    path('category/<slug:category_slug>/', views.product_list, name='category_products'), # Assuming product_list handles category filtering
    path('tag/<slug:tag_slug>/', views.product_list, name='tag_products'), # Assuming product_list handles tag filtering
    path('categories/', views.category_list, name='category_list'),
    path('import-products/', views.import_products_from_excel, name='import_products'),

    # Worker Product Audit URLs
    path('worker/products/', views.worker_product_list, name='worker_product_list'),
    path('worker/product/<uuid:product_id>/audit/', views.worker_product_audit_view, name='worker_product_audit'),
]
