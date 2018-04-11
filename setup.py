import os
import sys

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = """Tis But A Scratch
"""

requires = [
    #'pyqt5',
    ]

setup(name='tbas',
      author='CJ Niemira',
      author_email='siege@siege.org',
      version='0.1',
      description='Tis But A Scratch',
      long_description=README,
      classifiers=[
          "Programming Language :: Python",
      ],
      url='https://github.com/cniemira/tbas',
      keywords='games',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      entry_points="""\
      [console_scripts]
      tbas = tbas.cli:main
      tbas-gui = tbas.gui:main
      """,
      )
