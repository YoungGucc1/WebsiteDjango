from django import forms

class ProductImportForm(forms.Form):
    excel_file = forms.FileField(label='Select Excel file')
