import plugins


def _initialise():
    plugins.register_commands_argument_preprocessor_group(
        "exampleT",
        {r"^@@\w+" : test_resolver})

def test_resolver(*dummys):
    return "!HELLOWORLD!"
