from setuptools import find_packages, setup


setup(
    name="pp-agent",
    version="0.2.0",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    entry_points={"console_scripts": ["pp-agent=pp_agent.cli.main:main"]},
)
