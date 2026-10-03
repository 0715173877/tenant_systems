import datetime
from decimal import Decimal
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView, View
from django.urls import reverse_lazy
from django.contrib import messages
from django.shortcuts import redirect, render, get_object_or_404
from django.db.models import Sum, Count, Q, F
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django import forms
from .models import Expense, ExpenseCategory, Purchase, StockItem, StockMovement
from properties.models import Property
from properties.access import get_accessible_properties, get_accessible_property_ids
from django.forms import ModelForm
from django.utils import timezone


# ─────────────────────────────────────────────
#  Data-isolation helpers
# ─────────────────────────────────────────────

class FinanceScopedMixin(LoginRequiredMixin):
    """Scope a CBV queryset to the properties the current user can access.

    ``property_filter`` is the ORM lookup that reaches a ``Property`` from the
    view's model (defaults to a direct ``property`` FK).
    """

    property_filter = "property__in"

    def get_property_queryset(self):
        return get_accessible_properties(self.request.user)

    def get_accessible_ids(self):
        return get_accessible_property_ids(self.request.user)

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(**{self.property_filter: self.get_property_queryset()})


class PurchaseCreateForm(forms.ModelForm):
    """Custom form for Purchase that adds stock_item field and auto-fills suggestions."""

    stock_item = forms.ModelChoiceField(
        queryset=StockItem.objects.filter(is_active=True),
        required=False,
        label="Link to Stock Item (optional)",
        help_text="Select an existing stock item to auto-update inventory. If none exists, you can create one in Stock first.",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Purchase
        fields = [
            "property", "stock_item", "item_name", "quantity",
            "unit_price", "supplier", "purchase_date",
            "receipt_number", "receipt_image", "notes",
        ]
        widgets = {
            "property": forms.Select(attrs={"class": "form-select"}),
            "item_name": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. Office chairs, Cleaning supplies",
                "data-autofill": "true",
            }),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "supplier": forms.TextInput(attrs={"class": "form-control", "placeholder": "Vendor or supplier name"}),
            "purchase_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "receipt_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Receipt or invoice #"}),
            "receipt_image": forms.FileInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        props = get_accessible_properties(user) if user else Property.objects.none()
        # Restrict the property field to the user's own properties.
        self.fields["property"].queryset = props
        # Restrict stock items to the user's properties (and chosen property when editing).
        stock_qs = StockItem.objects.filter(property__in=props, is_active=True)
        if self.instance.pk and self.instance.property_id:
            stock_qs = stock_qs.filter(property=self.instance.property)
        self.fields["stock_item"].queryset = stock_qs
        self.fields["item_name"].widget.attrs.update({
            "list": "stock-item-suggestions",
        })



# ─────────────────────────────────────────────
#  Expense Views
# ─────────────────────────────────────────────

class ExpenseListView(FinanceScopedMixin, ListView):
    model = Expense
    template_name = "finance/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset().select_related("property", "category", "created_by")
        expense_type = self.request.GET.get("expense_type")
        category = self.request.GET.get("category")
        property_id = self.request.GET.get("property")
        start_date = self.request.GET.get("start_date")
        end_date = self.request.GET.get("end_date")
        if expense_type:
            qs = qs.filter(expense_type=expense_type)
        if category:
            qs = qs.filter(category_id=category)
        if property_id:
            qs = qs.filter(property_id=property_id)
        if start_date:
            qs = qs.filter(expense_date__gte=start_date)
        if end_date:
            qs = qs.filter(expense_date__lte=end_date)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["current_type"] = self.request.GET.get("expense_type", "")
        ctx["current_category"] = self.request.GET.get("category", "")
        ctx["current_property"] = self.request.GET.get("property", "")
        ctx["start_date"] = self.request.GET.get("start_date", "")
        ctx["end_date"] = self.request.GET.get("end_date", "")
        ctx["categories"] = ExpenseCategory.objects.filter(is_active=True)
        ctx["properties"] = self.get_property_queryset().filter(is_active=True)
        return ctx


class ExpenseCreateView(FinanceScopedMixin, CreateView):
    model = Expense
    fields = [
        "property", "category", "expense_type", "description",
        "amount", "payment_method", "transaction_reference",
        "expense_date", "vendor", "receipt_image", "notes",
    ]
    template_name = "finance/expense_form.html"
    success_url = reverse_lazy("finance:expense_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["property"].queryset = self.get_property_queryset()
        return form

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Expense recorded successfully.")
        return super().form_valid(form)


class ExpenseUpdateView(FinanceScopedMixin, UpdateView):
    model = Expense
    fields = [
        "property", "category", "expense_type", "description",
        "amount", "payment_method", "transaction_reference",
        "expense_date", "vendor", "receipt_image", "notes",
    ]
    template_name = "finance/expense_form.html"
    success_url = reverse_lazy("finance:expense_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["property"].queryset = self.get_property_queryset()
        return form

    def form_valid(self, form):
        messages.success(self.request, "Expense updated successfully.")
        return super().form_valid(form)


class ExpenseDeleteView(FinanceScopedMixin, DeleteView):
    model = Expense
    template_name = "finance/expense_confirm_delete.html"
    success_url = reverse_lazy("finance:expense_list")

    def form_valid(self, form):
        messages.success(self.request, "Expense deleted successfully.")
        return super().form_valid(form)


class ExpenseDetailView(FinanceScopedMixin, DetailView):
    model = Expense
    template_name = "finance/expense_detail.html"
    context_object_name = "expense"


# ─────────────────────────────────────────────
#  API / AJAX Endpoints
# ─────────────────────────────────────────────

class StockItemsByPropertyAPI(LoginRequiredMixin, View):
    """AJAX: Return stock items for a given property as JSON."""

    def get(self, request):
        property_id = request.GET.get("property")
        if not property_id:
            return JsonResponse([], safe=False)
        # Only allow properties the user can access; otherwise return nothing.
        if str(property_id) not in [str(i) for i in get_accessible_property_ids(request.user)]:
            return JsonResponse([], safe=False)
        items = StockItem.objects.filter(
            property_id=property_id, is_active=True
        ).values("id", "item_name", "quantity", "unit")
        return JsonResponse(list(items), safe=False)


# ─────────────────────────────────────────────
#  Purchase Views
# ─────────────────────────────────────────────


class PurchaseListView(FinanceScopedMixin, ListView):
    model = Purchase
    template_name = "finance/purchase_list.html"
    context_object_name = "purchases"
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset().select_related("property", "created_by", "stock_item")
        property_id = self.request.GET.get("property")
        start_date = self.request.GET.get("start_date")
        end_date = self.request.GET.get("end_date")
        if property_id:
            qs = qs.filter(property_id=property_id)
        if start_date:
            qs = qs.filter(purchase_date__gte=start_date)
        if end_date:
            qs = qs.filter(purchase_date__lte=end_date)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["current_property"] = self.request.GET.get("property", "")
        ctx["start_date"] = self.request.GET.get("start_date", "")
        ctx["end_date"] = self.request.GET.get("end_date", "")
        ctx["properties"] = self.get_property_queryset().filter(is_active=True)
        return ctx


class PurchaseCreateView(FinanceScopedMixin, CreateView):
    model = Purchase
    form_class = PurchaseCreateForm
    template_name = "finance/purchase_form.html"
    success_url = reverse_lazy("finance:purchase_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["stock_suggestions"] = StockItem.objects.filter(
            property__in=self.get_property_queryset(), is_active=True
        ).only("id", "item_name")
        return ctx

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        self.object = form.save()

        # If a stock item was selected, create the stock movement
        selected_stock = form.cleaned_data.get("stock_item")
        if selected_stock:
            StockMovement.objects.create(
                stock_item=selected_stock,
                movement_type="in",
                quantity=self.object.quantity,
                unit_price=self.object.unit_price,
                reference=f"Purchase #{self.object.id}",
                notes=f"Auto stock in from purchase: {self.object.item_name}",
                moved_by=self.request.user,
            )
            messages.success(self.request, "Purchase recorded and stock updated successfully.")
        else:
            # Fallback: try to auto-match by item name
            stock_item = StockItem.objects.filter(
                property=self.object.property,
                item_name__iexact=self.object.item_name,
                is_active=True,
            ).first()
            if stock_item:
                StockMovement.objects.create(
                    stock_item=stock_item,
                    movement_type="in",
                    quantity=self.object.quantity,
                    unit_price=self.object.unit_price,
                    reference=f"Purchase #{self.object.id}",
                    notes=f"Auto stock in from purchase: {self.object.item_name}",
                    moved_by=self.request.user,
                )
                messages.success(self.request, "Purchase recorded and stock updated automatically.")
            else:
                messages.success(self.request, "Purchase recorded successfully. Link to a stock item to track inventory.")

        return redirect(self.success_url)


class PurchaseUpdateView(FinanceScopedMixin, UpdateView):
    model = Purchase
    form_class = PurchaseCreateForm
    template_name = "finance/purchase_form.html"
    success_url = reverse_lazy("finance:purchase_list")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["stock_suggestions"] = StockItem.objects.filter(
            property__in=self.get_property_queryset(), is_active=True
        ).only("id", "item_name")
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Purchase updated successfully.")
        return super().form_valid(form)


class PurchaseDeleteView(FinanceScopedMixin, DeleteView):
    model = Purchase
    template_name = "finance/purchase_confirm_delete.html"
    success_url = reverse_lazy("finance:purchase_list")

    def form_valid(self, form):
        messages.success(self.request, "Purchase deleted successfully.")
        return super().form_valid(form)


class PurchaseDetailView(FinanceScopedMixin, DetailView):
    model = Purchase
    template_name = "finance/purchase_detail.html"
    context_object_name = "purchase"


# ─────────────────────────────────────────────
#  Stock Views
# ─────────────────────────────────────────────

class StockItemListView(FinanceScopedMixin, ListView):
    model = StockItem
    template_name = "finance/stock_list.html"
    context_object_name = "stock_items"
    paginate_by = 10

    def get_queryset(self):
        qs = super().get_queryset().select_related("property")
        property_id = self.request.GET.get("property")
        status = self.request.GET.get("status")
        search = self.request.GET.get("search", "")
        if property_id:
            qs = qs.filter(property_id=property_id)
        if status == "in_stock":
            qs = qs.filter(quantity__gt=F("low_stock_threshold"))
        elif status == "low":
            qs = qs.filter(quantity__gt=0, quantity__lte=F("low_stock_threshold"))
        elif status == "out":
            qs = qs.filter(quantity__lte=0)
        if search:
            qs = qs.filter(item_name__icontains=search)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["current_property"] = self.request.GET.get("property", "")
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["search"] = self.request.GET.get("search", "")
        ctx["properties"] = self.get_property_queryset().filter(is_active=True)
        ctx["needs_reorder_count"] = self.get_queryset().filter(
            is_active=True, low_stock_threshold__gt=0,
            quantity__lte=F("low_stock_threshold"),
        ).count()
        return ctx


class StockItemCreateView(FinanceScopedMixin, CreateView):
    model = StockItem
    fields = ["property", "item_name", "unit", "quantity", "low_stock_threshold", "unit_cost", "location", "supplier", "expiry_date", "notes", "is_active"]
    template_name = "finance/stock_form.html"
    success_url = reverse_lazy("finance:stock_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["property"].queryset = self.get_property_queryset()
        return form

    def form_valid(self, form):
        messages.success(self.request, "Stock item created successfully.")
        return super().form_valid(form)


class StockItemUpdateView(FinanceScopedMixin, UpdateView):
    model = StockItem
    fields = ["property", "item_name", "unit", "quantity", "low_stock_threshold", "unit_cost", "location", "supplier", "expiry_date", "notes", "is_active"]
    template_name = "finance/stock_form.html"
    success_url = reverse_lazy("finance:stock_list")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["property"].queryset = self.get_property_queryset()
        return form

    def form_valid(self, form):
        messages.success(self.request, "Stock item updated successfully.")
        return super().form_valid(form)


class StockItemDeleteView(FinanceScopedMixin, DeleteView):
    model = StockItem
    template_name = "finance/stock_confirm_delete.html"
    success_url = reverse_lazy("finance:stock_list")

    def form_valid(self, form):
        messages.success(self.request, "Stock item deleted successfully.")
        return super().form_valid(form)


class StockMovementView(FinanceScopedMixin, ListView):
    """View all stock movements."""
    model = StockMovement
    template_name = "finance/stock_movement_list.html"
    context_object_name = "movements"
    paginate_by = 20
    property_filter = "stock_item__property__in"

    def get_queryset(self):
        qs = super().get_queryset().select_related(
            "stock_item", "stock_item__property", "moved_by"
        )
        stock_item_id = self.request.GET.get("stock_item")
        mov_type = self.request.GET.get("movement_type")
        if stock_item_id:
            qs = qs.filter(stock_item_id=stock_item_id)
        if mov_type:
            qs = qs.filter(movement_type=mov_type)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["current_stock_item"] = self.request.GET.get("stock_item", "")
        ctx["current_movement_type"] = self.request.GET.get("movement_type", "")
        ctx["stock_items"] = StockItem.objects.filter(
            property__in=self.get_property_queryset(), is_active=True
        )
        return ctx


class StockMovementScopedMixin(FinanceScopedMixin):
    """Restrict the ``stock_item`` choice field to the user's properties."""

    property_filter = "stock_item__property__in"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["stock_item"].queryset = StockItem.objects.filter(
            property__in=self.get_property_queryset(), is_active=True
        )
        return form

    def get_scoped_stock_item(self, stock_item_id):
        return get_object_or_404(
            StockItem,
            id=stock_item_id,
            property__in=self.get_property_queryset(),
        )


class StockMovementCreateView(StockMovementScopedMixin, CreateView):
    model = StockMovement
    fields = ["stock_item", "movement_type", "quantity", "unit_price", "reference", "notes"]
    template_name = "finance/stock_movement_form.html"
    success_url = reverse_lazy("finance:stock_movements")

    def form_valid(self, form):
        form.instance.moved_by = self.request.user
        messages.success(self.request, "Stock movement recorded successfully.")
        return super().form_valid(form)


class StockMovementInView(StockMovementScopedMixin, CreateView):
    """Quick stock-in form."""
    model = StockMovement
    fields = ["stock_item", "quantity", "unit_price", "reference", "notes"]
    template_name = "finance/stock_movement_form.html"
    success_url = reverse_lazy("finance:stock_list")

    def get_initial(self):
        initial = super().get_initial()
        initial["movement_type"] = "in"
        stock_item_id = self.request.GET.get("stock_item")
        if stock_item_id:
            initial["stock_item"] = self.get_scoped_stock_item(stock_item_id)
        return initial

    def form_valid(self, form):
        form.instance.moved_by = self.request.user
        form.instance.movement_type = "in"
        messages.success(self.request, "Stock received successfully.")
        return super().form_valid(form)


class StockMovementOutView(StockMovementScopedMixin, CreateView):
    """Quick stock-out form."""
    model = StockMovement
    fields = ["stock_item", "quantity", "reference", "notes"]
    template_name = "finance/stock_movement_form.html"
    success_url = reverse_lazy("finance:stock_list")

    def get_initial(self):
        initial = super().get_initial()
        initial["movement_type"] = "out"
        stock_item_id = self.request.GET.get("stock_item")
        if stock_item_id:
            initial["stock_item"] = self.get_scoped_stock_item(stock_item_id)
        return initial

    def form_valid(self, form):
        form.instance.moved_by = self.request.user
        form.instance.movement_type = "out"
        form.instance.unit_price = form.instance.stock_item.unit_cost
        # Check if enough stock
        if form.instance.stock_item.quantity < form.instance.quantity:
            messages.error(
                self.request,
                f"Not enough stock! Only {form.instance.stock_item.quantity} {form.instance.stock_item.unit} available."
            )
            return self.form_invalid(form)
        messages.success(self.request, "Stock taken out successfully.")
        return super().form_valid(form)


# ─────────────────────────────────────────────
#  Stock Detail & Adjustment Views
# ─────────────────────────────────────────────

class StockItemDetailView(FinanceScopedMixin, DetailView):
    """View a single stock item with its movement history."""
    model = StockItem
    template_name = "finance/stock_detail.html"
    context_object_name = "stock_item"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["today"] = datetime.date.today()
        return ctx


class StockItemAdjustView(LoginRequiredMixin, View):
    """Adjust stock quantity by adding or removing."""
    template_name = "finance/stock_adjust.html"

    def get_stock_item(self, request, pk):
        return get_object_or_404(
            StockItem, pk=pk, property__in=get_accessible_properties(request.user)
        )

    def get(self, request, pk):
        stock_item = self.get_stock_item(request, pk)
        return render(request, self.template_name, {
            "stock_item": stock_item,
            "form": StockAdjustForm(stock_item=stock_item),
        })

    def post(self, request, pk):
        stock_item = self.get_stock_item(request, pk)
        form = StockAdjustForm(request.POST, stock_item=stock_item)
        if form.is_valid():
            adjustment_type = form.cleaned_data["adjustment_type"]
            quantity_change = form.cleaned_data["quantity_change"]
            reason = form.cleaned_data.get("reason", "")

            movement_type = "in" if adjustment_type == "addition" else "out"
            old_qty = stock_item.quantity

            # Create the movement record
            StockMovement.objects.create(
                stock_item=stock_item,
                movement_type=movement_type,
                quantity=quantity_change,
                unit_price=stock_item.unit_cost,
                reference=f"Manual adjustment: {reason}" if reason else "Manual adjustment",
                notes=reason,
                moved_by=request.user,
            )

            messages.success(
                request,
                f"{'Added' if adjustment_type == 'addition' else 'Removed'} {quantity_change} "
                f"{stock_item.unit} from {stock_item.item_name}. "
                f"New quantity: {stock_item.quantity}"
            )
            return redirect("finance:stock_detail", pk=stock_item.pk)

        return render(request, self.template_name, {
            "stock_item": stock_item,
            "form": form,
        })


# ─────────────────────────────────────────────
#  Dedicated Stock Out View
# ─────────────────────────────────────────────

class StockOutForm(ModelForm):
    class Meta:
        model = StockMovement
        fields = ["stock_item", "quantity", "reference", "notes"]
        widgets = {
            "stock_item": forms.Select(attrs={"class": "form-select"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "reference": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Maintenance, Room 12"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Why are these items being taken out?"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stock_item"].queryset = StockItem.objects.filter(
            property__in=get_accessible_properties(user), is_active=True
        )


class StockOutView(LoginRequiredMixin, View):
    """Dedicated stock-out view – pick property, item, qty, reason."""

    template_name = "finance/stock_out_form.html"

    def get_properties(self, request):
        return get_accessible_properties(request.user).filter(is_active=True)

    def get(self, request):
        property_id = request.GET.get("property")
        stock_item_id = request.GET.get("stock_item")
        initial = {}
        if property_id:
            initial["property"] = property_id
        if stock_item_id:
            initial["stock_item"] = stock_item_id
        return render(request, self.template_name, {
            "form": StockOutForm(initial=initial, user=request.user),
            "properties": self.get_properties(request),
            "selected_property": property_id or "",
            "selected_stock_item": stock_item_id or "",
        })

    def post(self, request):
        form = StockOutForm(request.POST, user=request.user)
        if form.is_valid():
            movement = form.save(commit=False)
            movement.movement_type = "out"
            movement.moved_by = request.user
            movement.unit_price = movement.stock_item.unit_cost

            # Check stock availability
            if movement.stock_item.quantity < movement.quantity:
                messages.error(
                    request,
                    f"Not enough stock! Only {movement.stock_item.quantity} {movement.stock_item.unit} available."
                )
                return render(request, self.template_name, {
                    "form": form,
                    "properties": self.get_properties(request),
                    "selected_property": request.POST.get("property", ""),
                    "selected_stock_item": request.POST.get("stock_item", ""),
                })

            movement.save()
            messages.success(
                request,
                f"Stock out recorded: {movement.quantity} {movement.stock_item.unit} of {movement.stock_item.item_name} taken out."
            )
            return redirect("finance:stock_list")

        return render(request, self.template_name, {
            "form": form,
            "properties": self.get_properties(request),
            "selected_property": request.POST.get("property", ""),
            "selected_stock_item": request.POST.get("stock_item", ""),
        })


class StockAdjustForm(forms.Form):
    ADJUSTMENT_CHOICES = [
        ("addition", "Addition (Add Stock)"),
        ("removal", "Removal (Remove Stock)"),
    ]

    adjustment_type = forms.ChoiceField(
        choices=ADJUSTMENT_CHOICES,
        widget=forms.RadioSelect,
        initial="addition",
    )
    quantity_change = forms.DecimalField(
        max_digits=10, decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        help_text="Enter a positive number to add or remove from current stock.",
    )
    reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        self.stock_item = kwargs.pop("stock_item", None)
        super().__init__(*args, **kwargs)

    def clean_quantity_change(self):
        qty = self.cleaned_data.get("quantity_change")
        return qty


# ─────────────────────────────────────────────
#  Comprehensive Report
# ─────────────────────────────────────────────

class FinanceReportView(LoginRequiredMixin, TemplateView):
    template_name = "finance/report.html"

    def get_property_queryset(self):
        return get_accessible_properties(self.request.user)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = datetime.date.today()
        start_date = self.request.GET.get("start_date", str(today.replace(day=1)))
        end_date = self.request.GET.get("end_date", str(today))
        property_id = self.request.GET.get("property")
        report_type = self.request.GET.get("report_type", "all")

        props = self.get_property_queryset()

        # Filter conditions – always scoped to the user's own properties.
        expense_filter = {"expense_date__gte": start_date, "expense_date__lte": end_date, "property__in": props}
        purchase_filter = {"purchase_date__gte": start_date, "purchase_date__lte": end_date, "property__in": props}
        from payments.models import Payment
        income_filter = {
            "payment_date__gte": start_date,
            "payment_date__lte": end_date,
            "lease__unit__block__property__in": props,
        }

        if property_id:
            expense_filter["property_id"] = property_id
            purchase_filter["property_id"] = property_id
            income_filter["lease__unit__block__property_id"] = property_id

        # ─── Income ───
        income_qs = Payment.objects.filter(**income_filter)
        total_income = income_qs.aggregate(total=Sum("amount"))["total"] or 0
        completed_income = income_qs.filter(status="completed").aggregate(total=Sum("amount"))["total"] or 0

        income_by_type = list(
            income_qs.values("payment_type")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )

        # ─── Expenses ───
        expense_qs = Expense.objects.filter(**expense_filter)
        total_expenses = expense_qs.aggregate(total=Sum("amount"))["total"] or 0

        expenses_by_type = list(
            expense_qs.values("expense_type")
            .annotate(total=Sum("amount"), count=Count("id"))
            .order_by("-total")
        )

        # ─── Purchases ───
        purchase_qs = Purchase.objects.filter(**purchase_filter)
        total_purchases = purchase_qs.aggregate(total=Sum("total_cost"))["total"] or 0

        # ─── Summary ───
        net_income = completed_income - total_expenses - total_purchases

        # ─── Daily breakdown ───
        daily = []
        if report_type in ("all", "income"):
            daily_income = list(
                income_qs.values("payment_date")
                .annotate(total=Sum("amount"))
                .order_by("payment_date")
            )
            for d in daily_income:
                d["type"] = "income"
            daily.extend(daily_income)

        if report_type in ("all", "expenses"):
            daily_expenses = list(
                expense_qs.values("expense_date")
                .annotate(total=Sum("amount"))
                .order_by("expense_date")
            )
            for d in daily_expenses:
                d["type"] = "expense"
                d["payment_date"] = d.pop("expense_date")
            daily.extend(daily_expenses)

        if report_type in ("all", "purchases"):
            daily_purchases = list(
                purchase_qs.values("purchase_date")
                .annotate(total=Sum("total_cost"))
                .order_by("purchase_date")
            )
            for d in daily_purchases:
                d["type"] = "purchase"
                d["payment_date"] = d.pop("purchase_date")
            daily.extend(daily_purchases)

        # Sort daily entries by date
        daily.sort(key=lambda x: x.get("payment_date", ""))

        ctx.update({
            "start_date": start_date,
            "end_date": end_date,
            "selected_property": property_id,
            "report_type": report_type,
            "properties": self.get_property_queryset().filter(is_active=True),
            # Income
            "total_income": total_income,
            "completed_income": completed_income,
            "income_by_type": income_by_type,
            # Expenses
            "total_expenses": total_expenses,
            "expenses_by_type": expenses_by_type,
            # Purchases
            "total_purchases": total_purchases,
            # Net
            "net_income": net_income,
            "daily": daily,
            "expense_count": expense_qs.count(),
            "income_count": income_qs.count(),
            "purchase_count": purchase_qs.count(),
        })
        return ctx
