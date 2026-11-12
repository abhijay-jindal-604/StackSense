"""Source keys contributed by the hosting layer task.

Same shape as kb/sources.py: key -> (title, https url, ISO accessed date). Merged by kb/sources.py.
"""

_A = "2026-11-13"

SOURCES: dict = {
    "hst_apprunner_change": ("AWS App Runner availability change (no new customers from 30 Apr 2026)", "https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html", _A),
    "hst_ecs_express": ("Amazon ECS Express Mode (App Runner replacement)", "https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-overview.html", _A),
    "hst_azure_appservice_overview": ("Azure App Service overview (.NET, Java, Node.js, Python, PHP, custom containers)", "https://learn.microsoft.com/en-us/azure/app-service/overview", _A),
    "hst_outposts": ("AWS Outposts", "https://aws.amazon.com/outposts/", _A),
    "hst_azure_local": ("Azure Local", "https://learn.microsoft.com/en-us/azure/azure-local/overview", _A),
    "hst_gdc": ("Google Distributed Cloud", "https://cloud.google.com/distributed-cloud", _A),
    "hst_openshift_disconnected": ("Red Hat OpenShift: installing in a disconnected environment", "https://docs.redhat.com/en/documentation/openshift_container_platform/latest/html/disconnected_environments/index", _A),
    "hst_firebase_app_hosting": ("Firebase App Hosting", "https://firebase.google.com/docs/app-hosting", _A),
    "hst_ec2_docs": ("Amazon EC2", "https://docs.aws.amazon.com/ec2/", _A),
    "hst_azure_vm_docs": ("Azure Virtual Machines", "https://learn.microsoft.com/en-us/azure/virtual-machines/", _A),
    "hst_gce_docs": ("Google Compute Engine", "https://cloud.google.com/compute/docs", _A),
    "hst_do_droplets": ("DigitalOcean Droplets", "https://docs.digitalocean.com/products/droplets/", _A),
    "hst_nginx_docs": ("nginx documentation", "https://nginx.org/en/docs/", _A),
    "hst_cf_workers_limits": ("Cloudflare Workers limits and runtime", "https://developers.cloudflare.com/workers/platform/limits/", _A),
    "hst_azure_swa_regions": ("Azure Static Web Apps FAQ and hosting regions", "https://learn.microsoft.com/en-us/azure/static-web-apps/overview", _A),
    "hst_shopify_data": ("Shopify privacy and data processing", "https://www.shopify.com/legal/dpa", _A),
}
