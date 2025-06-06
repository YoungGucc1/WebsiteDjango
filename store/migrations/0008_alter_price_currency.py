# Generated by Django 5.1.7 on 2025-05-30 20:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0007_warehouse_stock_counterparty_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='price',
            name='currency',
            field=models.CharField(choices=[('KZT', 'Казахстанский тенге'), ('USD', 'Доллар США'), ('EUR', 'Евро'), ('RUB', 'Российский рубль'), ('OTHER', 'Other Currency')], db_index=True, default='KZT', help_text='Currency of the price', max_length=10),
        ),
    ]
