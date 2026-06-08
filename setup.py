from setuptools import find_packages, setup


setup(
    name="pp-agent",
    version="0.1.0a1",
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.9",
    install_requires=["rank-bm25>=0.2.2,<0.3"],
    entry_points={"console_scripts": ["pp-agent=pp_agent.cli.main:main"]},
)
