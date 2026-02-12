def classFactory(iface):
    from .plugin import StripeHatchingPlugin
    return StripeHatchingPlugin(iface)
