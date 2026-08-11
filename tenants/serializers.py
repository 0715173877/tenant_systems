from rest_framework import serializers
from .models import Tenant, Lease


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = "__all__"


class LeaseSerializer(serializers.ModelSerializer):
    tenant_name = serializers.CharField(source="tenant.full_name", read_only=True)
    unit_display = serializers.CharField(source="unit.__str__", read_only=True)

    class Meta:
        model = Lease
        fields = "__all__"
