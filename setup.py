from setuptools import setup, find_packages

setup(
    name="reddit-dl",
    version="0.1",
    description="A minimal gallery-dl fork focused on Reddit extraction",
    packages=find_packages(),
    install_requires=["requests>=2.0"],
    entry_points={
        "console_scripts": [
            "reddit-dl=reddit_dl.extractor:main",
        ]
    },
)