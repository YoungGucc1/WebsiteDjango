from django.urls import path
from . import views

app_name = 'store'

urlpatterns = [
    path('', views.home, name='home'),
    path('products/', views.ProductListView.as_view(), name='product_list'),
    path('product/<slug:product_slug>/', views.ProductDetailView.as_view(), name='product_detail'),
    path('category/<slug:category_slug>/', views.ProductListView.as_view(), name='category_products'),
    path('tag/<slug:tag_slug>/', views.ProductListView.as_view(), name='tag_products'),
    path('categories/', views.category_list, name='category_list'),
] 