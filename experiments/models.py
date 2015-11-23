from django.db import models
from django.core.serializers.json import DjangoJSONEncoder
from django.conf import settings
from django.utils.safestring import mark_safe

from jsonfield import JSONField

import waffle
from waffle.models import Flag

import random
import json

from experiments.dateutils import now
from experiments import conf


CONTROL_STATE = 0
ENABLED_STATE = 1
TRACK_STATE = 3

STATES = (
    (CONTROL_STATE, 'Default/Control'),
    (ENABLED_STATE, 'Enabled'),
    (TRACK_STATE, 'Track'),
)


class Experiment(models.Model):
    name = models.CharField(
        primary_key=True, max_length=128,
        help_text='The experiment name')
    description = models.TextField(
        default="", blank=True, null=True,
        help_text='A brief description of this experiment')
    alternatives = JSONField(default={}, blank=True)
    relevant_chi2_goals = models.TextField(
        default="", null=True, blank=True,
        choices=((goal, goal) for goal in conf.ALL_GOALS),
        verbose_name='Chi-squared test',
        help_text=mark_safe(
            '<a href="http://en.wikipedia.org/wiki/Chi-squared_test" '
            'target="_blank">Used when optimising for conversion rate.</a>'))
    relevant_mwu_goals = models.TextField(
        default="", null=True, blank=True,
        choices=((goal, goal) for goal in conf.ALL_GOALS),
        verbose_name='Mann-Whitney U',
        help_text=mark_safe(
            '<a href="http://en.wikipedia.org/wiki/Mann%E2%80%93Whitney_U" '
            'target="_blank">Used when optimising for number of times '
            'users perform an action. (Advanced)</a>'))
    relevant_chi2_goals = models.TextField(default="", null=True, blank=True)
    relevant_mwu_goals = models.TextField(default="", null=True, blank=True)

    state = models.IntegerField(default=CONTROL_STATE, choices=STATES)
    start_date = models.DateTimeField(default=now, blank=True, null=True, db_index=True)
    end_date = models.DateTimeField(blank=True, null=True)

    @staticmethod
    def enabled_experiments():
        return Experiment.objects.filter(
            state__in=[ENABLED_STATE, SWITCH_STATE])

    def is_displaying_alternatives(self):
        if self.state == CONTROL_STATE:
            return False
        elif self.state == ENABLED_STATE:
            return True
        elif self.state == TRACK_STATE:
            return True
        else:
            raise Exception("Invalid experiment state %s!" % self.state)

    def is_accepting_new_users(self):
        if self.state == CONTROL_STATE:
            return False
        elif self.state == ENABLED_STATE:
            return True
        elif self.state == TRACK_STATE:
            return waffle.flag_is_active(request, self.switch_key)
        else:
            raise Exception("Invalid experiment state %s!" % self.state)

    @property
    def switch(self):
        if self.switch_key and conf.SWITCH_AUTO_CREATE:
            try:
                return Flag.objects.get(name=self.switch_key)
            except Flag.DoesNotExist:
                pass
        return None

    def ensure_alternative_exists(self, alternative, weight=None):
        if alternative not in self.alternatives:
            self.alternatives[alternative] = {}
            self.alternatives[alternative]['enabled'] = True
            self.save()
        if weight is not None and 'weight' not in self.alternatives[alternative]:
            self.alternatives[alternative]['weight'] = float(weight)
            self.save()

    @property
    def default_alternative(self):
        for alternative, alternative_conf in self.alternatives.iteritems():
            if alternative_conf.get('default'):
                return alternative
        return conf.CONTROL_GROUP

    def set_default_alternative(self, alternative):
        for alternative_name, alternative_conf in self.alternatives.iteritems():
            if alternative_name == alternative:
                alternative_conf['default'] = True
            elif 'default' in alternative_conf:
                del alternative_conf['default']

    def random_alternative(self):
        if all('weight' in alt for alt in self.alternatives.values()):
            return weighted_choice([(name, details['weight']) for name, details in self.alternatives.items()])
        else:
            return random.choice(self.alternatives.keys())

    def increment_participant_count(self, alternative_name,
                                    participant_identifier):
        # Increment experiment_name:alternative:participant counter
        counter_key = PARTICIPANT_KEY % (self.name, alternative_name)
        counters.increment(counter_key, participant_identifier)

    def increment_goal_count(self, alternative_name, goal_name,
                             participant_identifier, count=1):
        # Increment experiment_name:alternative:participant counter
        counter_key = GOAL_KEY % (self.name, alternative_name, goal_name)
        counters.increment(counter_key, participant_identifier, count)

    def remove_participant(self, alternative_name, participant_identifier):
        # Remove participation record
        counter_key = PARTICIPANT_KEY % (self.name, alternative_name)
        counters.clear(counter_key, participant_identifier)

        # Remove goal records
        for goal_name in conf.ALL_GOALS:
            counter_key = GOAL_KEY % (self.name, alternative_name, goal_name)
            counters.clear(counter_key, participant_identifier)

    def participant_count(self, alternative):
        return counters.get(PARTICIPANT_KEY % (self.name, alternative))

    def goal_count(self, alternative, goal):
        return counters.get(GOAL_KEY % (self.name, alternative, goal))

    def participant_goal_frequencies(self, alternative,
                                     participant_identifier):
        for goal in conf.ALL_GOALS:
            yield goal, counters.get_frequency(
                GOAL_KEY % (self.name, alternative, goal),
                participant_identifier)

    def goal_distribution(self, alternative, goal):
        return counters.get_frequencies(
            GOAL_KEY % (self.name, alternative, goal))

    def __unicode__(self):
        return self.name

    def to_dict(self):
        info = self._meta.app_label, self._meta.module_name
        data = {
            'name': self.name,
            'edit_url': reverse('admin:%s_%s_results' % info,
                                args=(self.name,)),
            'start_date': self.start_date,
            'end_date': self.end_date,
            'state': self.state,
            'description': self.description,
            'relevant_chi2_goals': self.relevant_chi2_goals,
            'relevant_mwu_goals': self.relevant_mwu_goals,
            'default_alternative': self.default_alternative,
            'alternatives': ','.join(self.alternatives.keys()),
        }
        return data

    def to_dict_serialized(self):
        return json.dumps(self.to_dict(), cls=DjangoJSONEncoder)

    def save(self, *args, **kwargs):
        # Create new flag
        if self.switch_key and conf.SWITCH_AUTO_CREATE:
            try:
                Flag.objects.get(name=self.switch_key)
            except Flag.DoesNotExist:
                Flag.objects.create(
                    name=self.switch_key,
                    note=self.description)

        if not self.switch_key and self.state == 2:
            self.state = 0

        if self.state == 0:
            self.end_date = now()
        else:
            self.end_date = None

        super(Experiment, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Delete existing enrollments
        self.enrollment_set.all().delete()

        # Delete existing flag
        if self.switch_key and conf.SWITCH_AUTO_CREATE:
            try:
                Flag.objects.filter(name=self.switch_key).delete()
            except Flag.DoesNotExist:
                pass

        super(Experiment, self).delete(*args, **kwargs)


class Enrollment(models.Model):
    """ A participant in a split testing experiment """
    user = models.ForeignKey(getattr(settings, 'AUTH_USER_MODEL', 'auth.User'))
    experiment = models.ForeignKey(Experiment)
    enrollment_date = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(null=True)
    alternative = models.CharField(max_length=50)

    class Meta:
        unique_together = ('user', 'experiment')

    def __unicode__(self):
        return u'%s - %s' % (self.user, self.experiment)


def weighted_choice(choices):
    total = sum(w for c, w in choices)
    r = random.uniform(0, total)
    upto = 0
    for c, w in choices:
        upto += w
        if upto >= r:
            return c
