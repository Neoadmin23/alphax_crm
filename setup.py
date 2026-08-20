from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="alphax_crm",
    version="0.13.4",
    description="Compliance-grade CRM automation for AlphaX on Frappe/ERPNext.",
    author="Neotec Integrated Solutions",
    author_email="support@neotec.ai",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
