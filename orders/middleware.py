from django.conf import settings
from .models import Tenant, TenantContext

class TenantMiddleware:
    """
    Middleware that identifies the current tenant context from:
    1. A custom HTTP header: 'X-Tenant-ID' (useful for API requests).
    2. The subdomain of the request host (useful for SaaS hosting).
    3. Fallback to the first tenant in DEBUG mode for local testing.
    
    Sets the current tenant ID in the thread-safe & async-safe ContextVar
    and cleans it up at the end of the request lifecycle.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant_id = None

        # 1. Check custom X-Tenant-ID header first
        tenant_header = request.headers.get('X-Tenant-ID')
        if tenant_header:
            try:
                tenant_id = int(tenant_header)
            except ValueError:
                pass

        # 2. If no header, extract tenant subdomain from the host name
        if not tenant_id:
            host_parts = request.get_host().split('.')
            if len(host_parts) > 2:
                # E.g. tenantA.example.com or tenantA.localhost:8000
                subdomain = host_parts[0]
                tenant = Tenant.objects.filter(subdomain=subdomain).first()
                if tenant:
                    tenant_id = tenant.id

        # 3. Fallback to the first tenant in local development for convenience
        if not tenant_id and settings.DEBUG:
            tenant = Tenant.objects.first()
            if tenant:
                tenant_id = tenant.id

        # Bind the tenant context for this request lifecycle
        token = None
        if tenant_id:
            token = TenantContext.set_current_tenant_id(tenant_id)
        
        try:
            response = self.get_response(request)
            return response
        finally:
            # Clean up/Reset the ContextVar to prevent memory leaks and cross-request state bleeding
            if token:
                TenantContext.clear()
