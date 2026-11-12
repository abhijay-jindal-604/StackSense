"""Source keys contributed by the backend layer task.

Same shape as kb/sources.py: key -> (title, https url, ISO accessed date). Merged by kb/sources.py.
Every URL answered HTTP 200 on 2026-11-13; the ones used for hard-filter facts (regions, attestations) were read.
"""

_A = "2026-11-13"

SOURCES: dict = {
    "nodejs_releases": ("Node.js - Previous releases (LTS schedule)", "https://nodejs.org/en/about/previous-releases", _A),
    "eol_laravel": ("endoflife.date - Laravel", "https://endoflife.date/laravel", _A),
    "eol_phoenix": ("endoflife.date - Phoenix Framework", "https://endoflife.date/phoenix-framework", _A),
    "eol_nestjs": ("endoflife.date - NestJS", "https://endoflife.date/nestjs", _A),
    "ktor_docs": ("Ktor documentation", "https://ktor.io/docs/welcome.html", _A),
    "go_chi_docs": ("chi - lightweight router for Go HTTP services", "https://go-chi.io/", _A),
    "hono_docs": ("Hono documentation (Workers, Deno, Bun, Node.js)", "https://hono.dev/docs/", _A),
    "azure_functions_docs": ("Azure Functions overview", "https://learn.microsoft.com/en-us/azure/azure-functions/functions-overview", _A),
    "azure_functions_pricing": ("Azure Functions pricing", "https://azure.microsoft.com/en-us/pricing/details/functions/", _A),
    "gcf_docs": ("Cloud Run functions (formerly Cloud Functions) overview", "https://cloud.google.com/functions/docs/concepts/overview", _A),
    "gcf_pricing": ("Cloud Run functions pricing", "https://cloud.google.com/functions/pricing", _A),
    "lambda_pricing": ("AWS Lambda pricing", "https://aws.amazon.com/lambda/pricing/", _A),
    "appwrite_docs": ("Appwrite documentation", "https://appwrite.io/docs", _A),
    "appwrite_regions": ("Appwrite Cloud regions (Bangalore listed as coming soon)", "https://appwrite.io/docs/products/network/regions", _A),
    "appwrite_compliance": ("Appwrite compliance (SOC 2 Type II)", "https://appwrite.io/docs/advanced/platform/compliance", _A),
    "appwrite_pricing": ("Appwrite pricing", "https://appwrite.io/pricing", _A),
    "supabase_dpa": ("Supabase Data Processing Addendum (GDPR)", "https://supabase.com/legal/dpa", _A),
    "shopify_pricing": ("Shopify pricing (INR list prices)", "https://www.shopify.com/pricing", _A),
    "django_release_52": ("Django 5.2 release notes (LTS)", "https://docs.djangoproject.com/en/5.2/releases/5.2/", _A),
    "laravel_releases": ("Laravel 13 release notes", "https://laravel.com/docs/13.x/releases", _A),
}
