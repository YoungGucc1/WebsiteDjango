# Django E-Commerce Store

A modern e-commerce platform built with Django 5.1.7.

## Features

- Product catalog with categories, tags, and images
- Responsive design with Bootstrap 5
- Product filtering by category and tags
- Admin interface for managing products, categories, and more
- Image processing and optimization
- SEO-friendly URLs

## Tech Stack

- Django 5.1.7
- Bootstrap 5
- Python 3.x
- SQLite (default, can be changed to other databases)
- Pillow for image processing

## Installation

1. Clone the repository
```bash
git clone <repository-url>
cd WebsiteDjango
```

2. Create a virtual environment and activate it
```bash
python -m venv venv
# On Windows
.\venv\Scripts\activate
# On Unix or MacOS
source venv/bin/activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Run migrations
```bash
python manage.py migrate
```

5. Create a superuser
```bash
python manage.py createsuperuser
```

6. Run the development server
```bash
python manage.py runserver
```

7. Visit `http://127.0.0.1:8000/` in your browser to see the site
8. Visit `http://127.0.0.1:8000/admin/` to access the admin panel

## Project Structure

- `store/` - Main Django app containing models, views, and templates
- `ecommerce/` - Django project settings
- `media/` - User-uploaded files (product images, etc.)
- `static/` - Static files (CSS, JavaScript, etc.)

## Models

1. **BaseModel** - Abstract base class with common fields
2. **Image** - Image model with processing capabilities
3. **Category** - Product categories with hierarchical structure
4. **Tag** - Tags for products
5. **Price** - Product prices with currency support
6. **Product** - Main product model with relationships to other models

## Usage

### Adding Products

1. First, add images through the admin panel
2. Create categories and tags
3. Create products, associating them with categories, tags, and images
4. Add prices for products

### Frontend

- Homepage displays featured products and categories
- Products page shows all products with category filtering
- Product detail page shows product information, images, and related products

## License

[MIT License](LICENSE)

## Future Development

Planned features:
- Shopping cart functionality
- User authentication and profiles
- Order processing
- Payment gateway integration
- Search functionality
- Wishlist feature
- Reviews and ratings 