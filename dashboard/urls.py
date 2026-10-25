from django.urls import path
from . import views

app_name = 'dashboard'

urlpatterns = [
    path('', views.home, name='home'),
    path('explore/', views.explore, name='explore'),
    path('content/<int:pk>/', views.content_detail, name='content_detail'),
path('insights/', views.insights, name='insights'),
]
