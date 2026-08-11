from rest_framework import serializers
from .models import Guest, Booking


class GuestSerializer(serializers.ModelSerializer):
    class Meta:
        model = Guest
        fields = "__all__"


class BookingSerializer(serializers.ModelSerializer):
    guest_name = serializers.CharField(source="guest.full_name", read_only=True)
    unit_display = serializers.CharField(source="unit.__str__", read_only=True)

    class Meta:
        model = Booking
        fields = "__all__"
        read_only_fields = ["total_amount"]
