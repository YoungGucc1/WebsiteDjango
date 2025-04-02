from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, DetailView
from .models import Product, Category, Tag

def home(request):
    """Homepage view showing featured products"""
    featured_products = Product.objects.filter(is_featured=True, is_active=True)[:8]
    categories = Category.objects.all()[:6]
    
    context = {
        'featured_products': featured_products,
        'categories': categories,
        'page_title': 'Home',
    }
    return render(request, 'store/home.html', context)

class ProductListView(ListView):
    """View for listing all products, can be filtered by category"""
    model = Product
    template_name = 'store/product_list.html'
    context_object_name = 'products'
    paginate_by = 12
    
    def get_queryset(self):
        queryset = Product.objects.filter(is_active=True)
        
        # Filter by category if provided in URL
        category_slug = self.kwargs.get('category_slug')
        if category_slug:
            category = get_object_or_404(Category, slug=category_slug)
            queryset = queryset.filter(category=category)
            
        # Filter by tag if provided in URL
        tag_slug = self.kwargs.get('tag_slug')
        if tag_slug:
            tag = get_object_or_404(Tag, slug=tag_slug)
            queryset = queryset.filter(tags=tag)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Add category info if filtering by category
        category_slug = self.kwargs.get('category_slug')
        if category_slug:
            category = get_object_or_404(Category, slug=category_slug)
            context['category'] = category
            context['page_title'] = f'Products in {category.name}'
        else:
            context['page_title'] = 'All Products'
            
        # Add tag info if filtering by tag
        tag_slug = self.kwargs.get('tag_slug')
        if tag_slug:
            tag = get_object_or_404(Tag, slug=tag_slug)
            context['tag'] = tag
            context['page_title'] = f'Products tagged with {tag.name}'
            
        # Add categories for sidebar
        context['categories'] = Category.objects.all()
        
        return context

class ProductDetailView(DetailView):
    """View for showing product details"""
    model = Product
    template_name = 'store/product_detail.html'
    context_object_name = 'product'
    slug_url_kwarg = 'product_slug'
    
    def get_queryset(self):
        return Product.objects.filter(is_active=True)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        product = self.get_object()
        
        # Add related products
        context['related_products'] = Product.objects.filter(
            category=product.category,
            is_active=True
        ).exclude(id=product.id)[:4]
        
        context['page_title'] = product.name
        return context

def category_list(request):
    """View for listing all categories"""
    categories = Category.objects.all()
    return render(request, 'store/category_list.html', {
        'categories': categories,
        'page_title': 'Categories',
    })
