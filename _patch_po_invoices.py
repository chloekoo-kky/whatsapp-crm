from pathlib import Path

invoices = Path(r"C:\Users\kwany\DjangoProjects\distributorplatform\app\inventory\templates\inventory\partials\invoices_tab.html")
text = invoices.read_text(encoding="utf-8")
old = """        </div>
    </div>

    {# --- Purchase orders --- #}
    <div class="border-t border-gray-200 pt-8 mt-10">
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4">
            <div>
                <h4 class="text-xl font-semibold text-gray-700">Purchase Orders</h4>
                <p class="text-sm text-gray-500 mt-1">Supplier quotations for ordering — convert to an invoice when goods are confirmed.</p>
            </div>
            <button type="button" @click="$dispatch('open-create-quotation-modal')"
                    class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 shadow-sm">
                + Create order
            </button>
        </div>
        <div x-data="legacyQuotationsData()"
             x-init="init()"
             @refresh-data.window="if ($event.detail.tab === 'invoices') fetchQuotations(1)">
            {% include 'inventory/partials/legacy_quotations_table.html' %}
        </div>
    </div>
</div>"""
new = """        </div>
    </div>
</div>

{# --- Purchase orders --- #}
<div x-data="legacyQuotationsData()"
     x-init="init()"
     @refresh-data.window="if ($event.detail.tab === 'invoices') fetchQuotations(1)"
     class="border-t border-gray-200 pt-8 mt-10">
    <div class="flex flex-col md:flex-row justify-between items-start md:items-center mb-6 gap-4">
        <div>
            <h4 class="text-xl font-semibold text-gray-700">Purchase Orders</h4>
            <p class="text-sm text-gray-500 mt-1">Supplier quotations for ordering — convert to an invoice when goods are confirmed.</p>
        </div>
        <button type="button" @click="$dispatch('open-create-quotation-modal')"
                class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 shadow-sm">
            + Create order
        </button>
    </div>
    {% include 'inventory/partials/legacy_quotations_table.html' %}
</div>"""
if old not in text:
    raise SystemExit("pattern not found")
text = text.replace(old, new, 1)
text = text.replace(
    "@refresh-data.window=\"if ($event.detail.tab === 'invoices') fetchInvoices()\"",
    "@refresh-data.window=\"if ($event.detail.tab === 'invoices') fetchInvoices(1)\"",
    1,
)
invoices.write_text(text, encoding="utf-8")
print("patched invoices_tab.html")
