from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import ListView, DetailView
from .models import Product, Category, Tag, Price
from .forms import ProductImportForm
import pandas as pd
from django.db import transaction
from django.contrib import messages
from decimal import Decimal

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

@transaction.atomic # Ensure all or nothing for database operations
def import_products_from_excel(request):
    if request.method == 'POST':
        form = ProductImportForm(request.POST, request.FILES)
        if form.is_valid():
            excel_file = request.FILES['excel_file']
            try:
                df = pd.read_excel(excel_file)

                # Sanitize column names from the DataFrame (strip spaces)
                original_columns = list(df.columns)
                sanitized_columns = [col.strip() for col in original_columns]
                df.columns = sanitized_columns
                
                # Store a mapping from original (potentially with spaces) to sanitized for error messages if needed
                # col_map = dict(zip(original_columns, sanitized_columns))

                # Expected column names (should be clean, no extra spaces here)
                # And 'Selling price', 'Purchase price' from screenshot.
                col_product_name = 'Name' 
                col_article_number = 'Article Number' 
                col_category_name = 'Category'       
                col_selling_price = 'Selling price'  
                col_purchase_price = 'Purchase price'

                # Optional columns (examples, user can have more based on Product model)
                col_description = 'Description' 
                col_short_description = 'Short Description'
                col_product_name_2 = 'Product Name 2' # Or 'name_2' from model, if user wants to map it

                required_excel_columns = [
                    col_product_name, 
                    col_article_number, 
                    col_category_name, 
                    col_selling_price, 
                    col_purchase_price
                ]
                missing_excel_columns = [col for col in required_excel_columns if col not in df.columns]
                
                if missing_excel_columns:
                    messages.error(request, f"Missing required columns in Excel: {', '.join(missing_excel_columns)}. Expected: {', '.join(required_excel_columns)}")
                    return redirect('import_products')

                products_created_count = 0
                products_updated_count = 0
                errors = []

                for index, row in df.iterrows():
                    try:
                        # Required fields from Excel based on user feedback and screenshot
                        product_name_val = row[col_product_name]
                        article_number_val = row[col_article_number]
                        category_name_val = row[col_category_name]
                        selling_price_val = row[col_selling_price]
                        purchase_price_val = row[col_purchase_price]

                        # Check for empty but present required values
                        if pd.isna(product_name_val) or \
                           pd.isna(article_number_val) or \
                           pd.isna(category_name_val) or \
                           pd.isna(selling_price_val) or \
                           pd.isna(purchase_price_val):
                            errors.append(f"Row {index + 2}: Missing data in one of the required columns ('{col_product_name}', '{col_article_number}', '{col_category_name}', '{col_selling_price}', '{col_purchase_price}').")
                            continue
                        
                        # Convert to string and strip whitespace
                        product_name_str = str(product_name_val).strip()
                        article_number_str = str(article_number_val).strip()
                        category_name_str = str(category_name_val).strip()

                        if not product_name_str or not article_number_str or not category_name_str: # Prices are numeric, already checked by pd.isna
                             errors.append(f"Row {index + 2}: Required text fields ('{col_product_name}', '{col_article_number}', '{col_category_name}') cannot be empty after stripping whitespace.")
                             continue

                        # Get or create category
                        category, cat_created = Category.objects.get_or_create(
                            name=category_name_str,
                            defaults={'name': category_name_str} # Ensure name is passed for creation
                        )
                        if cat_created:
                            messages.info(request, f"Category '{category.name}' was created.")

                        # Prepare product defaults from optional Excel columns
                        product_defaults = {
                            'name': product_name_str,
                            'category': category,
                            'is_active': True # Default to active
                        }
                        # Optional: name_2 (Product.name_2)
                        if col_product_name_2 in df.columns and pd.notna(row[col_product_name_2]):
                            product_defaults['name_2'] = str(row[col_product_name_2]).strip()
                        # Optional: description (Product.description)
                        if col_description in df.columns and pd.notna(row[col_description]):
                            product_defaults['description'] = str(row[col_description]).strip()
                        # Optional: short_description (Product.short_description)
                        if col_short_description in df.columns and pd.notna(row[col_short_description]):
                            product_defaults['short_description'] = str(row[col_short_description]).strip()
                        
                        # Add other optional fields from Product model here if they are in the Excel
                        # e.g., is_featured, etc.
                        # if 'Is Featured' in df.columns and pd.notna(row['Is Featured']):
                        #    product_defaults['is_featured'] = bool(row['Is Featured'])


                        # Create or update product using article_number
                        product, product_created = Product.objects.update_or_create(
                            article_number=article_number_str,
                            defaults=product_defaults
                        )
                        
                        if product_created:
                            products_created_count += 1
                        else:
                            products_updated_count += 1
                        
                        # Create or update Selling Price
                        Price.objects.update_or_create(
                            product=product,
                            price_type=Price.PriceType.SELLING,
                            currency='USD', # Assuming USD, make this dynamic if currency can vary per row/import
                            defaults={
                                'amount': Decimal(selling_price_val),
                                'is_active': True,  # Selling price is usually active
                                'description': 'Imported Selling Price' # Optional: add a default description
                            }
                        )
                        
                        # Create or update Purchase Price
                        Price.objects.update_or_create(
                            product=product,
                            price_type=Price.PriceType.PURCHASE,
                            currency='USD', # Assuming USD
                            defaults={
                                'amount': Decimal(purchase_price_val),
                                'is_active': True, # Or False, depending on business logic
                                'description': 'Imported Purchase Price' # Optional: add a default description
                            }
                        )

                    except Exception as e:
                        errors.append(f"Row {index + 2}: Error processing product '{row.get(col_product_name, 'N/A')}' (Article: {row.get(col_article_number, 'N/A')}): {str(e)}")
                
                if products_created_count > 0:
                    messages.success(request, f"Successfully created {products_created_count} products.")
                if products_updated_count > 0:
                    messages.success(request, f"Successfully updated {products_updated_count} products.")
                if not products_created_count and not products_updated_count and not errors:
                     messages.info(request, "No new products were created or updated. The file might be empty or products already exist.")
                
                for error_msg in errors:
                    messages.error(request, error_msg)

                return redirect('import_products') # Redirect to the same page to show messages

            except pd.errors.EmptyDataError:
                messages.error(request, "The uploaded Excel file is empty.")
            except Exception as e:
                messages.error(request, f"Error processing Excel file: {str(e)}")
        else:
            messages.error(request, "Invalid file submitted.")
            
    else: # GET request
        form = ProductImportForm()
        
    return render(request, 'store/import_products.html', {
        'form': form,
        'page_title': 'Import Products from Excel'
    })
