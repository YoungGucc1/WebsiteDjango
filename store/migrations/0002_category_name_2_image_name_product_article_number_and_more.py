# Generated by Django 5.1.7 on 2025-04-02 09:00

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='name_2',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='image',
            name='name',
            field=models.CharField(blank=True, db_index=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='article_number',
            field=models.CharField(blank=True, db_index=True, help_text='Product article/SKU number', max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='name_2',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='tag',
            name='name_2',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
