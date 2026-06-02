"""
Curated external link library for HitPay content.

Keyed by market code (SG / MY / PH / SEA).
Each entry: {"name": str, "url": str, "use_when": str}
Competitor entries carry "competitor": True — require rel="nofollow" and are only
included in comparison / listicle articles.
"""

EXTERNAL_LINKS: dict[str, dict[str, list[dict]]] = {
    "SG": {
        "regulators": [
            {"name": "Monetary Authority of Singapore (MAS)", "url": "https://www.mas.gov.sg", "use_when": "Any compliance, licensing, or regulatory mention"},
            {"name": "Payment Services Act", "url": "https://www.mas.gov.sg/regulation/acts/payment-services-act", "use_when": "Mentioning SG payment licensing"},
            {"name": "Enterprise Singapore", "url": "https://www.enterprisesg.gov.sg", "use_when": "SME growth or business support context"},
        ],
        "payment_methods": [
            {"name": "PayNow", "url": "https://www.mas.gov.sg/development/e-payments/paynow", "use_when": "Mentioning PayNow"},
            {"name": "GrabPay", "url": "https://www.grab.com/sg/pay/", "use_when": "Mentioning GrabPay"},
            {"name": "ShopeePay", "url": "https://shopee.sg/m/shopeepay", "use_when": "Mentioning ShopeePay"},
            {"name": "Atome", "url": "https://www.atome.sg", "use_when": "Mentioning Atome BNPL"},
            {"name": "Visa", "url": "https://www.visa.com.sg", "use_when": "Mentioning Visa card acceptance"},
            {"name": "Mastercard", "url": "https://www.mastercard.com.sg", "use_when": "Mentioning Mastercard acceptance"},
            {"name": "UPI", "url": "https://www.npci.org.in/what-we-do/upi/product-overview", "use_when": "Mentioning UPI for Indian tourists/expats"},
        ],
        "integrations": [
            {"name": "Shopify", "url": "https://help.shopify.com/en/manual/payments", "use_when": "Shopify integration articles only"},
            {"name": "WooCommerce", "url": "https://woocommerce.com/documentation/", "use_when": "WooCommerce integration articles only"},
            {"name": "Xero", "url": "https://central.xero.com", "use_when": "Xero accounting integration articles only"},
            {"name": "Zapier", "url": "https://zapier.com/how-it-works", "use_when": "Automation articles only"},
        ],
        "research": [
            {"name": "Singapore Department of Statistics", "url": "https://www.singstat.gov.sg", "use_when": "Citing Singapore business, retail, or economic data"},
            {"name": "Statista Singapore e-commerce", "url": "https://www.statista.com/topics/2531/e-commerce-in-singapore/", "use_when": "Citing Singapore e-commerce market size or growth figures"},
            {"name": "World Bank financial inclusion", "url": "https://www.worldbank.org/en/topic/financialinclusion", "use_when": "Citing financial inclusion, unbanked population, or digital payments adoption data"},
            {"name": "Visa's economic empowerment research", "url": "https://www.visa.com.sg/visa-everywhere/innovation/digital-payments.html", "use_when": "Citing digital payments adoption or contactless payment trends"},
        ],
        "competitors": [
            {"name": "Airwallex", "url": "https://www.airwallex.com/sg", "competitor": True},
            {"name": "Fiuu", "url": "https://fiuu.com", "competitor": True},
            {"name": "Stripe", "url": "https://stripe.com", "competitor": True},
            {"name": "Red Dot Payment", "url": "https://reddotpayment.com", "competitor": True},
            {"name": "Adyen", "url": "https://www.adyen.com", "competitor": True},
            {"name": "Qashier", "url": "https://qashier.com/sg/", "competitor": True},
            {"name": "KPay", "url": "https://www.kpay-group.com/en-sg", "competitor": True},
            {"name": "EPOS", "url": "https://www.epos.com.sg", "competitor": True},
            {"name": "Koomi", "url": "https://koomi.com.sg", "competitor": True},
            {"name": "Revolut", "url": "https://www.revolut.com/en-SG", "competitor": True},
        ],
    },
    "MY": {
        "regulators": [
            {"name": "Bank Negara Malaysia", "url": "https://www.bnm.gov.my", "use_when": "Any compliance or regulatory mention"},
            {"name": "SME Corp Malaysia", "url": "https://www.smecorp.gov.my", "use_when": "SME growth or business support context"},
        ],
        "payment_methods": [
            {"name": "FPX", "url": "https://www.paynet.my/fpx.html", "use_when": "Mentioning FPX"},
            {"name": "DuitNow", "url": "https://www.paynet.my/duitnow.html", "use_when": "Mentioning DuitNow"},
            {"name": "GrabPay", "url": "https://www.grab.com/my/pay/", "use_when": "Mentioning GrabPay"},
            {"name": "Atome", "url": "https://www.atome.com.my", "use_when": "Mentioning Atome BNPL"},
            {"name": "Visa", "url": "https://www.visa.com.my", "use_when": "Mentioning Visa card acceptance"},
            {"name": "Mastercard", "url": "https://www.mastercard.com.my", "use_when": "Mentioning Mastercard acceptance"},
        ],
        "integrations": [
            {"name": "Shopify", "url": "https://help.shopify.com/en/manual/payments", "use_when": "Shopify integration articles only"},
            {"name": "WooCommerce", "url": "https://woocommerce.com/documentation/", "use_when": "WooCommerce integration articles only"},
            {"name": "Xero", "url": "https://central.xero.com", "use_when": "Xero accounting integration articles only"},
            {"name": "QuickBooks", "url": "https://quickbooks.intuit.com/learn-support/", "use_when": "QuickBooks integration articles only"},
        ],
        "research": [
            {"name": "PayNet Malaysia", "url": "https://www.paynet.my", "use_when": "Citing FPX, DuitNow, or Malaysian payment network transaction volumes"},
            {"name": "Malaysia Digital Economy Corporation (MDEC)", "url": "https://mdec.my", "use_when": "Citing Malaysia digital economy, e-commerce, or SME digitalisation data"},
            {"name": "Department of Statistics Malaysia", "url": "https://www.dosm.gov.my", "use_when": "Citing Malaysian business, retail, or economic statistics"},
            {"name": "Statista Malaysia e-commerce", "url": "https://www.statista.com/topics/2530/e-commerce-in-malaysia/", "use_when": "Citing Malaysia e-commerce market size or growth figures"},
            {"name": "World Bank financial inclusion", "url": "https://www.worldbank.org/en/topic/financialinclusion", "use_when": "Citing financial inclusion, unbanked population, or digital payments adoption data"},
        ],
        "competitors": [
            {"name": "Stripe", "url": "https://stripe.com", "competitor": True},
            {"name": "iPay88", "url": "https://www.ipay88.com", "competitor": True},
            {"name": "Razer Merchant Services", "url": "https://merchant.razer.com", "competitor": True},
            {"name": "Billplz", "url": "https://www.billplz.com", "competitor": True},
            {"name": "SenangPay", "url": "https://senangpay.com", "competitor": True},
            {"name": "eGHL", "url": "https://www.eghl.my", "competitor": True},
            {"name": "Fiuu", "url": "https://fiuu.com", "competitor": True},
            {"name": "StoreHub", "url": "https://www.storehub.com", "competitor": True},
            {"name": "Pine Labs", "url": "https://www.pinelabs.com", "competitor": True},
            {"name": "Curlec", "url": "https://curlec.com", "competitor": True},
        ],
    },
    "PH": {
        "regulators": [
            {"name": "Bangko Sentral ng Pilipinas", "url": "https://www.bsp.gov.ph", "use_when": "Any compliance or regulatory mention"},
        ],
        "payment_methods": [
            {"name": "GrabPay", "url": "https://www.grab.com/ph/pay/", "use_when": "Mentioning GrabPay"},
            {"name": "Maya", "url": "https://www.maya.ph", "use_when": "Mentioning Maya wallet"},
            {"name": "GCash", "url": "https://www.gcash.com", "use_when": "Mentioning GCash"},
            {"name": "Visa", "url": "https://www.visa.com.ph", "use_when": "Mentioning Visa card acceptance"},
            {"name": "Mastercard", "url": "https://www.mastercard.com.ph", "use_when": "Mentioning Mastercard acceptance"},
        ],
        "integrations": [
            {"name": "Shopify", "url": "https://help.shopify.com/en/manual/payments", "use_when": "Shopify integration articles only"},
            {"name": "WooCommerce", "url": "https://woocommerce.com/documentation/", "use_when": "WooCommerce integration articles only"},
        ],
        "research": [
            {"name": "Philippine Statistics Authority (PSA)", "url": "https://psa.gov.ph", "use_when": "Citing Philippine business, retail, or economic statistics"},
            {"name": "BSP payment system statistics", "url": "https://www.bsp.gov.ph/PaymentAndSettlement/PaymentSystemStatistics.aspx", "use_when": "Citing Philippine payment volumes, InstaPay, or PESONet transaction data"},
            {"name": "Statista Philippines e-commerce", "url": "https://www.statista.com/topics/9204/e-commerce-in-the-philippines/", "use_when": "Citing Philippines e-commerce market size or growth figures"},
            {"name": "World Bank financial inclusion", "url": "https://www.worldbank.org/en/topic/financialinclusion", "use_when": "Citing financial inclusion, unbanked population, or digital payments adoption data"},
        ],
        "competitors": [
            {"name": "PayMongo", "url": "https://www.paymongo.com", "competitor": True},
            {"name": "Xendit", "url": "https://www.xendit.co", "competitor": True},
            {"name": "DragonPay", "url": "https://www.dragonpay.ph", "competitor": True},
            {"name": "Paynamics", "url": "https://paynamics.com", "competitor": True},
            {"name": "2C2P", "url": "https://www.2c2p.com", "competitor": True},
            {"name": "PayPal", "url": "https://www.paypal.com", "competitor": True},
            {"name": "PesoPay", "url": "https://www.pesopay.com", "competitor": True},
        ],
    },
    "SEA": {
        "regulators": [
            {"name": "Monetary Authority of Singapore (MAS)", "url": "https://www.mas.gov.sg", "use_when": "Any compliance or regulatory mention in a multi-market context"},
        ],
        "payment_methods": [
            {"name": "Visa", "url": "https://www.visa.com", "use_when": "Mentioning Visa in a multi-market context"},
            {"name": "Mastercard", "url": "https://www.mastercard.com", "use_when": "Mentioning Mastercard in a multi-market context"},
        ],
        "integrations": [],
        "research": [
            {"name": "World Bank financial inclusion", "url": "https://www.worldbank.org/en/topic/financialinclusion", "use_when": "Citing financial inclusion, unbanked population, or digital payments adoption data"},
            {"name": "Statista SEA e-commerce", "url": "https://www.statista.com/outlook/emo/ecommerce/southeast-asia", "use_when": "Citing Southeast Asia e-commerce market size or regional growth figures"},
            {"name": "Google-Temasek e-Conomy SEA", "url": "https://economysea.withgoogle.com", "use_when": "Citing SEA internet economy, digital payments growth, or regional GMV data"},
        ],
        "competitors": [
            {"name": "Stripe", "url": "https://stripe.com", "competitor": True},
            {"name": "Adyen", "url": "https://www.adyen.com", "competitor": True},
            {"name": "Airwallex", "url": "https://www.airwallex.com", "competitor": True},
            {"name": "2C2P", "url": "https://www.2c2p.com", "competitor": True},
            {"name": "Fiuu", "url": "https://fiuu.com", "competitor": True},
            {"name": "Xendit", "url": "https://www.xendit.co", "competitor": True},
        ],
    },
}
