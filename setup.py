import re

import setuptools

# with open("docs/requirements.txt", "r") as stream:
#     extras_require_docs = stream.read().splitlines()

# with open("test/requirements.txt", "r") as stream:
#     extras_require_test = stream.read().splitlines()

extras_require = {
    # "docs": extras_require_docs,  # TODO: malamar[docs]
    # "test": extras_require_test,  # TODO: malamar[test]
}

packages = setuptools.find_packages()

_version_regex = r"^version(?:\s*:\s*str)?\s*=\s*('|\")((?:[0-9]+\.)*[0-9]+(?:\.?([a-z]+)(?:\.?[0-9])?)?)\1$"

with open("malamar/__init__.py") as stream:
    match = re.search(_version_regex, stream.read(), re.MULTILINE)

if not match:
    raise RuntimeError("could not find version")

version = match.group(2)

if match.group(3) is not None:
    try:
        import subprocess

        process = subprocess.Popen(["git", "rev-list", "--count", "HEAD"], stdout=subprocess.PIPE)
        out, _ = process.communicate()
        if out:
            version += out.decode("utf-8").strip()

        process = subprocess.Popen(["git", "rev-parse", "--short", "HEAD"], stdout=subprocess.PIPE)
        out, _ = process.communicate()
        if out:
            version += "+g" + out.decode("utf-8").strip()
    except Exception as e:
        pass


setuptools.setup(
    author="bijij",
    author_email="josh@josh-is.gay",
    description="Dependency Injection Framework for Python.",
    extras_require=extras_require,
    include_package_data=True,
    license="Apache Software License",
    name="malamar",
    packages=packages,
    python_requires=">=3.8.0",
    url="https://github.com/bijij/malamar",
    version=version,
)
