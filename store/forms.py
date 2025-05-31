from django import forms
from .models import Product, Image, WorkerProductAudit, Category, Tag, Price, Warehouse, Stock, Counterparty

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'

class ImageForm(forms.ModelForm):
    class Meta:
        model = Image
        fields = ['name', 'file_path', 'description', 'alt_text', 'type', 'is_main']

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = '__all__'

class TagForm(forms.ModelForm):
    class Meta:
        model = Tag
        fields = '__all__'

class PriceForm(forms.ModelForm):
    class Meta:
        model = Price
        fields = '__all__'

class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = '__all__'

class StockForm(forms.ModelForm):
    class Meta:
        model = Stock
        fields = '__all__'

class CounterpartyForm(forms.ModelForm):
    class Meta:
        model = Counterparty
        fields = '__all__'

class WorkerProductAuditForm(forms.ModelForm):
    photo_taken_upload = forms.ImageField(required=False, label="Upload Photo")

    class Meta:
        model = WorkerProductAudit
        fields = ['quantity_recorded', 'photo_taken_upload']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.photo_taken:
            # If a photo exists, make the upload field not required initially
            self.fields['photo_taken_upload'].required = False
        else:
            # If no photo exists (new audit or photo was removed), it's required
            self.fields['photo_taken_upload'].required = True
        
        # Add a class for styling
        self.fields['quantity_recorded'].widget.attrs.update({'class': 'form-control'})
        self.fields['photo_taken_upload'].widget.attrs.update({'class': 'form-control-file'})

    def clean(self):
        cleaned_data = super().clean()
        photo_upload = cleaned_data.get("photo_taken_upload")
        
        # If there's no existing photo and no new photo is uploaded, raise an error
        # This is an additional check because the 'required' attribute on the field
        # might not cover all cases, especially if the form is re-rendered.
        if not self.instance.photo_taken and not photo_upload:
            self.add_error('photo_taken_upload', "A photo is required.")
            
        return cleaned_data

    def save(self, commit=True):
        audit_instance = super().save(commit=False)
        photo_upload = self.cleaned_data.get('photo_taken_upload')

        if photo_upload:
            # Create a new Image instance for the uploaded photo
            image_name = f"audit_{audit_instance.product.slug}_{timezone.now().strftime('%Y%m%d%H%M%S')}"
            new_image = Image(
                name=image_name,
                file_path=photo_upload,
                type=Image.ImageType.AUDIT,
                alt_text=f"Audit photo for {audit_instance.product.name}"
            )
            if commit:
                new_image.save() # Save the image first
            audit_instance.photo_taken = new_image # Link it to the audit
        
        # The WorkerProductAudit model's save method handles setting is_completed and completed_at
        if commit:
            audit_instance.save()
        return audit_instance

# --- Image Search Settings Form ---
IMG_SIZE_OPTIONS = [
    ("any", "Any Size"), ("huge", "Huge"), ("icon", "Icon"), ("large", "Large"),
    ("medium", "Medium"), ("small", "Small"), ("xlarge", "XLarge"), ("xxlarge", "XXLarge")
]
IMG_TYPE_OPTIONS = [
    ("any", "Any Type"), ("clipart", "Clipart"), ("face", "Face"), ("lineart", "Lineart"),
    ("stock", "Stock"), ("photo", "Photo"), ("animated", "Animated")
]
IMG_COLOR_TYPE_OPTIONS = [
    ("any", "Any Color Type"), ("color", "Color"), ("gray", "Grayscale"), ("mono", "Monochrome")
]
FILE_TYPE_OPTIONS = [
    ("any", "Any File Type"), ("bmp", "BMP"), ("gif", "GIF"), ("jpg", "JPG"),
    ("png", "PNG"), ("svg", "SVG"), ("webp", "WEBP")
]
SAFE_SEARCH_OPTIONS = [
    ("off", "Off (Risky)"), ("active", "Active (Safe)"), ("high", "High"), ("medium", "Medium")
]

class ImageSearchSettingsForm(forms.Form):
    num_results = forms.IntegerField(
        label="Number of Images per Product",
        min_value=1,
        max_value=10, # Google API typically returns max 10 per request
        initial=3,
        help_text="How many images to attempt to download for each product (1-10)."
    )
    img_size = forms.ChoiceField(
        label="Image Size",
        choices=IMG_SIZE_OPTIONS,
        initial="large",
        required=True
    )
    img_type = forms.ChoiceField(
        label="Image Type",
        choices=IMG_TYPE_OPTIONS,
        initial="photo",
        required=True
    )
    img_color_type = forms.ChoiceField(
        label="Image Color Type",
        choices=IMG_COLOR_TYPE_OPTIONS,
        initial="any",
        required=True
    )
    file_type = forms.ChoiceField(
        label="File Type",
        choices=FILE_TYPE_OPTIONS,
        initial="jpg",
        required=True
    )
    safe_search = forms.ChoiceField(
        label="Safe Search Level",
        choices=SAFE_SEARCH_OPTIONS,
        initial="active",
        required=True
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': 'form-control mb-2'})
            if isinstance(field.widget, forms.Select):
                field.widget.attrs.update({'class': 'form-select mb-2'})
