# Copyright (c) 2016 Publisher, Inc. - All Rights Reserved.
# Unauthorized copying of this file, via any medium is strictly prohibited.
# Proprietary and confidential.
# Written by Sergio de Diego <sergio.dediego@outlook.com>, October 2016.

from django.db import models, transaction
from django.urls import reverse

from apps.group.caches import cache_bust, make_key, make_key_many
from apps.group.exceptions import GroupError, GroupMembershipError
from apps.group.signals import group_created

# Create your managers here.

class GroupManager(models.Manager):
    """
    Group model manager.
    """

    @transaction.atomic
    def create_new_group(self, user, name, access='PRIVATE'):
        """
        Create a new group defined by its name and access type.
        Group access is set as private ('PRIV') by default.
        When created send signal to set administrator permit to the group creator.
        """
        if not self.filter(name=name).exists():
            group, created = self.get_or_create(name=name, access=access)
            if created:
                response = group_created.send(sender=self.model.__class__, user=user, group=group)
                receiver, administrator = response[0]
                cache_bust([('groups', user.pk)])
                return group, administrator
            return False
        else:
            raise GroupError('Already exists a group with name \'{name}\''.format(name=name))

    def get_user_groups(self, user):
        """
        Return all group memberships for one user.
        """
        key = make_key('groups', user.pk)
        groups = cache.get(key)
        if groups is None:
            groups = self.filter(members=user).order_by('-date_joined')
            cache.set(key, groups)
        return groups

    def count_user_groups(self, user):
        """
        Count all groups the user belongs to.
        """
        count = self.get_user_groups(user).count()
        return count


class GroupMembershipManager(models.Manager):
    """
    GroupMembership model manager.
    """

    @transaction.atomic
    def add_membership(self, user, group, permit='PART'):
        """
        New group membership.
        If the group is public the user joins it automatically, whereas
        if it is private the user must be admitted by the group administrator
        via requeset approval.
        """
        if self.is_member(user, group):
            raise GroupMembershipError('User is already member of this group.')
        if group.access == 'PUBLIC':
            membership, created = self.get_or_create(member=user, group=group, permit=permit)
            if created:
                membership_created.send(sender=self.model)
                cache_bust([('groups', user.pk), ('memberships', group.pk)])
                return reverse('group:group_detail', kwargs={'group_id': group.pk})
        elif group.access == 'PRIVATE':
            return reverse('group:membership_request', kwargs={'group_id': group.pk})
        else:
            raise GroupError('Group access has to be either PUBLIC or PRIVATE.')

    @transaction.atomic
    def set_group_admin(self, user, group, permit='ADMIN'):
        """
        Set the creator of a group as administrator.
        There can only be one administrator in each group.
        """
        if isinstance(group, self.model.__class__):
            if not self.filter(group=group, permit=permit).exists():
                administrator = self.create(member=user, group=group, permit=permit)
                return administrator
            else:
                raise GroupError('The group already has one administrator.')
        return False

    def get_group_admin(self, group):
        """
        Return group administrator.
        """
        if isinstance(group, self.model.__class__):
            try:
                membership = self.selected_related('member').get(group=group, permit='ADMIN')
                administrator = membership.member
                return administrator
            except self.model.DoesNotExist:
                raise GroupError('Group has no administrator.')
        return False

    def memberships(self, group):
        """
        Return all group memberships and members.
        """
        keys = make_key_many([('memberships', group.pk), ('members', group.pk)])
        memberships = cache.get(keys.get('memberships'))
        members = cache.get(keys.get('members'))
        if memberships is None:
            memberships = self.selected_related('member').filter(group=group)
            cache.set(keys.get('memberships'), memberships)
        if members is None:
            members = [membership.member for membership in memberships]
            cache.set(keys.get('members'), members)
        return memberships, members

    #def members(self, group):
    #    """
    #    Return all group members.
    #    """
    #    key = make_key('members', group.pk)
    #    members = cache.get(key)
    #    if members is None:
    #        memberships = self.memberships(group)
    #        members = [membership.member for membership in memberships]
    #        cache.set(key, members)
    #    return members

    def count_group_members(self, group):
        """
        Count all members belonging to one group.
        """
        #count = len(self.members(group=group))
        memberships, members = self.memberships(group)
        count = memberships.count()
        return count

    def is_member(self, user, group):
        """
        Check if user is a group member.
        """
        if user.is_authenticated() and isinstance(group, self.model.__class__):
            key = make_key('members', group.pk)
            members = cache.get(key)
            if members is not None and user in members:
                return True
            else:
                try:
                    member = self.get(member=user, group=group)
                    return True
                except self.model.DoesNotExist:
                    return False
        return False

class GroupMembershipRequestManager(models.Manager):
    """
    GroupMembership model manager.
    """

    @transaction.atomic
    def send_membership_request(self, from_user, to_admin, group, message):
        """
        Send membership request to private group administrator to join.
        After trying to join a private group the user is redirected to
        membership request form if the group is private once checked the
        user is not already a group member.
        The membership request form saving executes this method.
        """
        if user.is_authenticated():
            request, created = self.get_or_create(from_user=from_user, to_administrator=to_admin, group=group, message=message)
            if not created:
                raise SendRequestError('Membership request for this group has already been sent.')
            cache_bust([('requests', to_admin.pk), ('sent_requests', from_user.pk)])
            membership_request_sent.send(sender=self.model.__class__)
            return request
        return False

    def requests(self, user):
        """
        Return all membership requests.
        """
        key = make_key('requests', user.pk)
        requests = cache.get(key)
        if requests is None:
            requests = self.filter(from_user=user)
            cache.set(key, requests)
        return requests

    def request_count(self, user):
        """
        Return all membership requests count.
        """
        #count = len(self.requests(user))
        count = self.requests(user).count()
        return count

    def rejected_requests(self, user):
        """
        Return all rejected membership requests.
        """
        key = make_key('rejected_requests', user.pk)
        rejected_requests = cache.get(key)
        if rejected_requests is None:
            rejected_requests = self.filter(Q(rejected__isnull=False) | Q(rejected=True), from_user=user)
            cache.set(key, rejected_requests)
        return rejected_requests

    def rejected_requests_count(self, user):
        """
        Return all rejected membership requests count.
        """
        #count = len(self.rejected_requests(user=user))
        count = self.rejected_requests(user).count()
        return count

    def unrejected_requests(self, user):
        """
        Return all unrejected membership requests.
        """
        key = make_key('unrejected_requests', user.pk)
        unrejected_requests = cache.get(key)
        if unrejected_requests is None:
            unrejected_requests = self.filter(Q(rejected__isnull=True) | Q(rejected=False), from_user=user)
            cache.set(key, unrejected_requests)
        return unrejected_requests

    def unrejected_requests_count(self, user):
        """
        Return all unrejected membership requests count.
        """
        #count = len(self.unrejected_requests(user=user))
        count = self.unrejected_requests(user).count()
        return count

    def viewed_requests(self, user):
        """
        Return all viewed membership requests.
        """
        key = make_key('viewed_requests', user.pk)
        viewed_requests = cache.get(key)
        if viewed_requests is None:
            viewed_requests = self.filter(Q(viewed__isnull=False) | Q(viewed=True), from_user=user)
            cache.set(key, viewed_requests)
        return viewed_requests

    def viewed_request_count(self, user):
        """
        Return all viewed membership requests count.
        """
        #count = len(self.viewed_requests(user=user))
        count = self.viewed_requests(user).count()
        return count

    def unviewed_requests(self, user):
        """
        Return all unviewed membership requests.
        """
        key = make_key('unviewed_requests', user.pk)
        unviewed_requests = cache.get(key)
        if unviewed_requests is None:
            unviewed_requests = self.filter(Q(viewed__isnull=True) | Q(viewed=False), from_user=user)
            cache.set(key, unviewed_requests)
        return unviewed_requests

    def unviewed_request_count(self, user):
        """
        Return all unviewed membership requests count.
        """
        #count = len(self.unviewed_requests(user=user))
        count = self.unviewed_requests(user).count()
        return count
