from rest_framework import serializers
from .models import Property, Block, Unit, UnitAmenity, PropertyStaff


class PropertySerializer(serializers.ModelSerializer):
    total_blocks = serializers.IntegerField(read_only=True)
    total_units = serializers.IntegerField(read_only=True)

    class Meta:
        model = Property
        fields = "__all__"


class UnitAmenitySerializer(serializers.ModelSerializer):
    class Meta:
        model = UnitAmenity
        fields = "__all__"


class BlockSerializer(serializers.ModelSerializer):
    unit_count = serializers.SerializerMethodField()

    class Meta:
        model = Block
        fields = "__all__"

    def get_unit_count(self, obj):
        return obj.units.count()


class UnitSerializer(serializers.ModelSerializer):
    block_name = serializers.CharField(source="block.name", read_only=True)
    property_name = serializers.CharField(
        source="block.property.name", read_only=True
    )
    amenity_list = UnitAmenitySerializer(source="amenities", many=True, read_only=True)

    effective_currency = serializers.SerializerMethodField()

    class Meta:
        model = Unit
        fields = "__all__"

    def get_effective_currency(self, obj):
        return obj.effective_currency


class PropertyStaffSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(
        source="user.get_full_name", read_only=True
    )

    class Meta:
        model = PropertyStaff
        fields = "__all__"
