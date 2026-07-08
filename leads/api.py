from datetime import datetime

from typing import List, Optional



from django.db.models import Q

from django.shortcuts import get_object_or_404

from ninja import Field, ModelSchema, Query, Router, Schema

from ninja.errors import HttpError



from leads.models import Lead, SearchQueryRecord

from leads.services import fetch_leads_from_serper



router = Router(tags=["leads"])





class LeadOut(ModelSchema):

    class Meta:

        model = Lead

        fields = [

            "id",

            "name",

            "phone_number",

            "phone_numbers",

            "address",

            "website",

            "shop_keyword",

            "category",

            "source_url",

            "is_processed",

            "is_chain",

            "chain_detected_internal",

            "chain_detected_ai",

            "location_count_estimate",

            "is_very_important",

            "whatsapp_draft",

            "search_city",

            "search_state",

            "search_country",

            "search_query",

            "created_at",

        ]





class LeadListOut(Schema):

    id: int

    name: str

    shop_keyword: str = ""

    category: str

    is_processed: bool = False

    is_chain: bool = False

    is_very_important: bool = False

    website: str = ""

    phone_number: str = ""

    search_city: Optional[str] = None

    search_state: Optional[str] = None

    search_country: Optional[str] = None

    search_query: Optional[str] = None

    created_at: datetime





class LeadFilters(Schema):

    shop_keyword: Optional[str] = Field(

        None, description="Substring match on the hunt keyword stored on the lead"

    )

    category: Optional[str] = Field(None, description="Lead category slug (e.g. fitness, cafe, invalid)")

    is_chain: Optional[bool] = Field(None, description="When true, only multi-location / chain rows")

    q: Optional[str] = Field(None, description="Search name / address")





class HuntIn(Schema):

    city: str = Field(..., min_length=1)

    shop_keyword: str = Field(

        default="",

        description="Free-text keyword for the hunt (e.g. fitness center, café). Required unless legacy shop_type is sent.",

    )

    shop_type: Optional[str] = Field(

        default=None,

        description="Deprecated alias for shop_keyword (Django dashboard body key).",

    )

    query: str = Field(

        default="",

        description="Maps query fragment; when empty, shop_keyword is used for Serper.",

    )

    state: str = Field(

        default="",

        description="Optional state/province appended to the Serper query after the city (disambiguation).",

    )

    country: str = Field(

        default="",

        description="Optional country appended to the Serper query after the city (disambiguation).",

    )

    log_search: bool = Field(

        default=True,

        description="When true, persist a SearchQueryRecord for dashboard-style history.",

    )

    limit: int = Field(default=100, ge=1, le=100)

    require_website: bool = Field(

        default=False,

        description="When true, only import listings that have a website or social profile URL (not Maps-only).",

    )

    exclude_keywords: Optional[list[str]] = Field(

        default=None,

        description="Skip listings whose name/address contains any of these terms (applied locally after Serper import).",

    )





class HuntOut(Schema):

    ok: bool

    created: int

    skipped_existing: int

    skipped_duplicate_phone: int = 0

    skipped_no_website: int = 0

    places_seen: int

    errors: List[str]

    message: str = ""

    search_record_id: Optional[int] = None





@router.get("/", response=List[LeadListOut])

def list_leads(request, filters: Query[LeadFilters]):

    qs = Lead.objects.all()

    if filters.shop_keyword:

        sk = filters.shop_keyword.strip()

        if sk:

            qs = qs.filter(shop_keyword__icontains=sk)

    if filters.category:

        qs = qs.filter(category=filters.category.lower())

    if filters.is_chain is not None:

        qs = qs.filter(is_chain=filters.is_chain)

    if filters.q:

        qq = filters.q.strip()

        if qq:

            qs = qs.filter(Q(name__icontains=qq) | Q(address__icontains=qq))

    return qs[:500]





@router.post("/hunt", response=HuntOut)

def hunt_leads(request, body: HuntIn):

    """Run Serper Maps hunt for a city + query and persist new leads."""

    try:

        raw_limit = request.GET.get("limit")

        if raw_limit is not None and str(raw_limit).strip() != "":

            try:

                num = max(1, min(int(raw_limit), 100))

            except ValueError:

                num = body.limit

        else:

            num = body.limit

        kw = (body.shop_keyword or body.shop_type or "").strip()

        if not kw:

            raise HttpError(400, "shop_keyword is required.") from None

        rec = None

        ctry = (body.country or "").strip()

        if body.log_search:

            rec = SearchQueryRecord.objects.create(

                keyword=kw[:160],

                maps_search_query=((body.query or "").strip() or kw)[:255],

                search_city=(body.city or "").strip()[:255],

                search_state=(body.state or "").strip()[:255],

                search_country=ctry[:255],

            )

        result = fetch_leads_from_serper(

            body.city,

            body.query,

            num=num,

            shop_keyword=kw,

            state=(body.state or "").strip(),

            country=ctry,

            search_query_record=rec,

            require_website=body.require_website,

            exclude_keywords=body.exclude_keywords,

        )

    except ValueError as exc:

        raise HttpError(400, str(exc)) from exc



    if result.errors and result.places_seen == 0 and result.created == 0:

        raise HttpError(502, "; ".join(result.errors[:3]) or "Hunt failed.")



    msg_parts = [

        f"Processed {result.places_seen} place(s).",

        f"Created {result.created}, already had {result.skipped_existing}.",

    ]

    if result.skipped_duplicate_phone:

        msg_parts.append(f"Skipped {result.skipped_duplicate_phone} duplicate phone(s).")

    return HuntOut(

        ok=True,

        created=result.created,

        skipped_existing=result.skipped_existing,

        skipped_duplicate_phone=result.skipped_duplicate_phone,

        skipped_no_website=result.skipped_no_website,

        places_seen=result.places_seen,

        errors=result.errors,

        message=" ".join(msg_parts),

        search_record_id=rec.pk if rec else None,

    )





@router.get("/{lead_id}", response=LeadOut)

def get_lead(request, lead_id: int):

    return get_object_or_404(Lead, pk=lead_id)





@router.get("/{lead_id}/", response=LeadOut)

def get_lead_trailing_slash(request, lead_id: int):

    return get_object_or_404(Lead, pk=lead_id)

