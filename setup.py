from setuptools import setup, find_packages
setup(
    name="commandment",
    version="0.1",
    description="Commandment is an Open Source Apple MDM server with support for managing iOS and macOS devices",
    packages=['commandment'],
    include_package_data=True,
    author="mosen",
    license="MIT",
    url="https://github.com/cmdmnt/commandment",
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.6'
    ],
    keywords='MDM',
    install_requires=[
        'acme==0.34.2',
        'alembic==1.4.2',
        'apns2-client==0.5.4',
        'asn1crypto==1.0.0',
        'authlib==0.11',
        'biplist==1.0.3',
        'blinker>=1.4',
        'cryptography==2.8.0',
        'flask==1.0.3',
        'flask-alembic==2.0.1',
        'flask-cors==3.0.4',
        'flask-jwt==0.3.2',
        'flask-marshmallow==0.10.1',
        'flask-rest-jsonapi==0.29.0',
        'flask-sqlalchemy==2.4.0',
        'marshmallow==2.18.0',
        'marshmallow-enum==1.4.1',
        'marshmallow-jsonapi==0.21.0',
        'marshmallow-sqlalchemy==0.16.3',
        'oscrypto==1.2.1',
        'passlib==1.7.1',
        'requests==2.22.0',
        'semver',
        'sqlalchemy==1.3.3',
        'typing==3.6.4'
    ],
    python_requires='>=3.6',
    tests_require=[
        # 'factory-boy==2.10.0',
        # 'faker==0.8.10',
        # 'mock==2.0.0',
        # 'mypy==0.560'
        # 'pytest==3.4.0',
        # 'pytest-runner==3.0'
    ],
    extras_requires={
        'ReST': [
            # 'sphinx-rtd-theme',
            # 'guzzle-sphinx-theme',
            # 'sadisplay==0.4.8',
            # 'sphinx==1.7.0b2',
            # 'sphinxcontrib-httpdomain==1.6.0',
            # 'sphinxcontrib-napoleon==0.6.1',
            # 'sphinxcontrib-plantuml==0.10',
        ],
        'macOS': [
            'pyobjc'
        ]
    },
    setup_requires=['pytest-runner'],
    entry_points={
        'console_scripts': [
            'commandment=commandment.cli:server',
            'appmanifest=commandment.pkg.appmanifest:main',
        ]
    },
    zip_safe=False
)


