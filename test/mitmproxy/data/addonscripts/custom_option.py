

class CustomOptionAddon:
    def load(self, loader):
        loader.add_option(
            name="custom_addon_option",
            typespec=int | None,
            default=None,
            help="A custom option registered by an addon.",
        )


addons = [CustomOptionAddon()]
