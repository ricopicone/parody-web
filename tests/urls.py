from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # the annotator and read-along mount alongside core, under the same book
    # prefix, and before it so their reserved segments read first
    path("", include("parody_web_readaloud.urls")),
    path("", include("parody_web_annotate.urls")),
    path("", include("parody_web.urls")),
]
