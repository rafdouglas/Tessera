def classFactory(iface):
    from .plugin import PercentageSplitPlugin
    return PercentageSplitPlugin(iface)
