import os
import sys

from django.conf import settings

import django

def runtests():
    test_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, test_dir)

    settings.configure(
        DEBUG=True,
        DATABASES={
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': 'test.db',
            }
        },
        CACHES={
            'default': {
                'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
            }
        },
        INSTALLED_APPS=('django.contrib.auth',
                        'django.contrib.contenttypes',
                        'django.contrib.sessions',
                        'django.contrib.admin',
                        'waffle',
                        'experiments',),
        ROOT_URLCONF='experiments.tests.urls',
        MIDDLEWARE_CLASSES = (
            'django.contrib.sessions.middleware.SessionMiddleware',
            'django.middleware.csrf.CsrfViewMiddleware',
            'django.contrib.auth.middleware.AuthenticationMiddleware',
            'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
        ),
    )
    django.setup()


    from django.test.utils import get_runner
    TestRunner = get_runner(settings)
    test_runner = TestRunner(verbosity=1, failfast=False)
    failures = test_runner.run_tests(['experiments', ])
    sys.exit(bool(failures))


if __name__ == '__main__':
    runtests()
