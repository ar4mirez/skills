from setuptools import find_packages, setup

setup(
    name="linkshort",
    version="0.3.0",
    packages=find_packages(),
    install_requires=open("requirements.txt").read().splitlines(),
)
