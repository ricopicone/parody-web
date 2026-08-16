from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # the annotator mounts alongside core, under the same book prefix
    path("", include("parody_web_annotate.urls")),
    path("", include("parody_web.urls")),
]
