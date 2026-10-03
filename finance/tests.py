from datetime import date

from django.test import TestCase
from django.urls import reverse

from config.test_factories import TwoLandlordFixtureMixin
from .models import Expense, StockItem


class FinanceFactoryMixin(TwoLandlordFixtureMixin):
    def setUp(self):
        super().setUp()
        self.expense_a = Expense.objects.create(
            property=self.property_a, expense_type="utilities",
            description="Water bill A", amount="50000.00", expense_date=date(2026, 2, 1),
        )
        self.expense_b = Expense.objects.create(
            property=self.property_b, expense_type="utilities",
            description="Water bill B", amount="50000.00", expense_date=date(2026, 2, 1),
        )
        self.stock_a = StockItem.objects.create(
            property=self.property_a, item_name="Toilet Paper", quantity="10",
        )
        self.stock_b = StockItem.objects.create(
            property=self.property_b, item_name="Toilet Paper", quantity="10",
        )


class FinanceIsolationTests(FinanceFactoryMixin, TestCase):
    def test_expense_list_is_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("finance:expense_list"))
        expenses = list(response.context["expenses"])
        self.assertIn(self.expense_a, expenses)
        self.assertNotIn(self.expense_b, expenses)

    def test_expense_detail_other_owner_404(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("finance:expense_detail", args=[self.expense_b.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_stock_list_is_scoped(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(reverse("finance:stock_list"))
        items = list(response.context["stock_items"])
        self.assertIn(self.stock_a, items)
        self.assertNotIn(self.stock_b, items)

    def test_stock_detail_other_owner_404(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("finance:stock_detail", args=[self.stock_b.id])
        )
        self.assertEqual(response.status_code, 404)

    def test_stock_api_only_returns_own_items(self):
        self.client.force_login(self.owner_a)
        response = self.client.get(
            reverse("finance:api_stock_items_by_property"),
            {"property": self.property_a.id},
        )
        self.assertEqual(response.status_code, 200)
        names = [item["item_name"] for item in response.json()]
        self.assertIn("Toilet Paper", names)

        # Owner A cannot request another owner's property items.
        response_b = self.client.get(
            reverse("finance:api_stock_items_by_property"),
            {"property": self.property_b.id},
        )
        self.assertEqual(response_b.json(), [])
