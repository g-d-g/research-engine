# groups.py
# For creating, managing and updating groups.

from datetime import datetime, timedelta
from google.appengine.ext import ndb
import generic, email_messages, projects

UPDATES_TO_DISPLAY = 30           # number of updates to display in the Overview tab


###########################
##   Datastore Objects   ##
###########################

class Groups(ndb.Model):
    name         = ndb.StringProperty(required = True)
    description  = ndb.TextProperty(required = False)
    members      = ndb.KeyProperty(repeated = True)
    started      = ndb.DateTimeProperty(auto_now_add = True)
    last_updated = ndb.DateTimeProperty(auto_now = True)

    def list_members(self):
        members_list = []
        for u_key in self.members:
            member = u_key.get()
            if member:
                members_list.append(member)
            else:
                logging.warning("Group with key (%s) contains a broken reference to member (%s)"
                                % (self.key, u_key))
        return members_list

    def user_is_member(self, user):
        result = False
        for u_key in self.members:
            if user.key == u_key: result = True
        return result

    def add_member(self, requesting_handler, user):
        if user.key in self.members: return False
        self.members.append(user.key)
        requesting_handler.log_and_put(self, "Adding a new member. ")
        user.my_groups.append(self.key)
        requesting_handler.log_and_put(user, "Adding a new group to my_groups property")
        return True

    def list_updates(self, requesting_handler, n = UPDATES_TO_DISPLAY):
        assert type(n) == int
        assert n > 0
        requesting_handler.log_read(GroupUpdates, "Requesting %s updates. " % n)
        updates = GroupUpdates.query(ancestor = self.key).order(-GroupUpdates.date).fetch(n)
        return updates

    def new_update(self, item):
        new_update = GroupUpdates(author = item.author,
                                  item   = item.key,
                                  parent = self.key)
        new_update.put()
        self.put()

# Should have a Group as parent
class GroupUpdates(ndb.Model):
    date   = ndb.DateTimeProperty(auto_now_add = True)
    author = ndb.KeyProperty(kind = generic.RegisteredUsers, required = True)
    item   = ndb.KeyProperty(required = True)

    def description_html(self, show_group_p = True):
        return generic.render_str("group_activity.html",
                                  author = self.author.get(),
                                  item = self.item,
                                  group = self.key.parent().get())

# Should have a Group as parent
class CalendarEvents(ndb.Model):
    start_date  = ndb.DateTimeProperty(required = True)     # Maybe later I'll add an "end_date"
    added       = ndb.DateTimeProperty(auto_now_add = True)
    author      = ndb.KeyProperty(required = True)
    description = ndb.TextProperty(required = False)

    def send_email_notifications(self):
        group   = self.key.parent().get()
        members = group.list_members()
        author  = self.author.get()
        for member in members:
            email_messages.send_new_calendar_event_notification(user = member, author = author,
                                                                group = group, event = self)
            

######################
##   Web Handlers   ##
######################

class GroupPage(generic.GenericPage):
    def get_group(self, group_id, log_message = ''):
        self.log_read(Groups, log_message)
        return Groups.get_by_id(int(group_id))

    def put_and_report(self, item, author, group, other_to_update = None):
        self.log_and_put(item)
        # Log user activity
        u_activity = generic.UserActivities(parent = author.key, item = item.key, relative_to = project.key, actv_kind = "Groups")
        self.log_and_put(u_activity)
        # Log group update
        g_update = GroupUpdates(parent = group.key, author = author.key, item = item.key)
        self.log_and_put(g_update)
        self.log_and_put(group)
        if other_to_update: self.log_and_put(other_to_update)
        return


class NewGroupPage(generic.GenericPage):
    def get(self):
        user = self.get_login_user()
        if not user:
            self.redirect("/login?goback=/new_group")
            return
        self.render("group_new.html")

    def post(self):
        user = self.get_login_user()
        if not user:
            self.redirect("/login?goback=/new_group")
            return
        kw = {
            "g_name" : self.request.get("g_name"),
            "g_description" : self.request.get("g_description")}
        have_error = False
        if not kw["g_name"]:
            have_error = True
            kw["error"] = "Please provide a name."
            kw["name_class"] = "has-error"
        groups = Groups.query(Groups.name == kw["g_name"]).fetch()
        if groups:
            for g in groups:
                if user.key in g.members:
                    have_error = True
                    kw["error"] = "You are already in a group named " + kw["g_name"]
                    kw["name_class"] = "has-error"
        if have_error:
            self.render("group_new.html", **kw)
        else:
            group = Groups(name = kw["g_name"],
                           description = kw["g_description"],
                           members = [user.key])
            group.put()
            user.my_groups.append(group.key)
            user.put()
            self.redirect("/g/%s" % group.key.integer_id())

class ViewGroupPage(GroupPage):
    def render(self, *a, **kw):
        GroupPage.render(self, overview_tab_class = "active", *a, **kw)

    def get(self, groupid):
        user = self.get_login_user()
        if not user:
            self.redirect("/login?goback=/g/%s" % groupid)
            return
        group = self.get_group(groupid)
        if not group or not group.user_is_member(user):
            self.render("404.html", info = "Group %s not found or you are not a member of this group." % groupid)
            return
        self.render("group_overview.html", group = group, user = user,
                    members = group.list_members(),
                    updates = group.list_updates(self))


class CalendarPage(GroupPage):
    def render(self, *a, **kw):
        GroupPage.render(self, calendar_tab_class = "active", *a, **kw)

    def get(self, groupid):
        user = self.get_login_user()
        if not user:
            self.redirect("/login?goback=/g/%s" % groupid)
            return
        group = self.get_group(groupid)
        if not group or not group.user_is_member(user):
            self.render("404.html", info = "Group %s not found or you are not a member of this group." % groupid)
            return
        display_date = datetime.today() - timedelta(days=1)
        events = CalendarEvents.query(ancestor = group.key).filter(CalendarEvents.start_date > display_date).order(CalendarEvents.start_date).fetch()
        self.render("group_calendar.html", group = group, user = user, events = events)


class CalendarNewTask(CalendarPage):
    def get(self, groupid):
        user = self.get_login_user()
        if not user:
            self.redirect("/login?goback=/g/%s" % groupid)
            return
        group = self.get_group(groupid)
        if not group or not group.user_is_member(user):
            self.render("404.html", info = "Group %s not found or you are not a member of this group." % groupid)
            return
        self.render("group_calendar_new_task.html", group = group, user = user)

    def post(self, groupid):
        user = self.get_login_user()
        if not user:
            self.redirect("/login?goback=/g/%s" % groupid)
            return
        group = self.get_group(groupid)
        if not group or not group.user_is_member(user):
            self.render("404.html", info = "Group %s not found or you are not a member of this group." % groupid)
            return
        kw = {"date" : self.request.get("date"),
              "description" : self.request.get("description")}
        have_error = False
        if not kw["date"] :
            have_error = True
            kw["error_message"] = "Please select a date for the event."
            kw["date_class"] = "has-error"
        elif not kw["description"]:
            have_error = True
            kw["error_message"] = "Please provide a description for the event."
            kw["description_class"] = "has-error"
        if have_error:
            self.render("group_calendar_new_task.html", group = group, user = user, **kw)
        else:
            new_event = CalendarEvents(start_date = datetime.strptime(kw["date"], "%d.%m.%Y %H:%M"),
                                       author = user.key,
                                       description = kw["description"],
                                       parent = group.key)
            new_event.put()
            group.new_update(new_event)
            new_event.send_email_notifications()
            self.redirect("/g/%s/calendar" % groupid)


class AdminPage(GroupPage):
    def get(self, groupid):
        user = self.get_login_user()
        if not user:
            self.redirect("/login?goback=/g/%s" % groupid)
            return
        group = self.get_group(groupid)
        if not group or not group.user_is_member(user):
            self.render("404.html", info = "Group %s not found or you are not a member of this group." % groupid)
            return
        self.render("group_admin.html", group = group, user = user, members = group.list_members())
 
    def post(self, groupid):
        user = self.get_login_user()
        if not user:
            self.redirect("/login?goback=/g/%s" % groupid)
            return
        group = self.get_group(groupid)
        if not group or not group.user_is_member(user):
            self.render("404.html", info = "Group %s not found or you are not a member of this group." % groupid)
            return
        kw = {"action" :self.request.get("action")}
        if kw["action"] == "invite":
            kw["username"] = self.request.get("username")
            invited_user = self.get_user_by_username(kw["username"].lower())
            if not invited_user:
                kw["error_message"] = "No username <em>%s</em> found" % kw["username"]
            elif not group.user_is_member(user):
                kw["error_message"] = "You are not a member of this group"
            elif invited_user.key in group.members:
                kw["error_message"] = "%s is already a member of %s" % (invited_user.username.capitalize(), group.name)
            else:
                email_messages.send_invitation_to_group(group = group,
                                                        inviting = user,
                                                        invited = invited_user)
                kw["message"] = "Invitation sent to <em>%s</em>" % invited_user.username.capitalize()
        else:
            kw["error_message"] = "Something went wring while processing your request."
        self.render("group_admin.html", group = group, user = user, members = group.list_members(), **kw)


class InvitedPage(GroupPage):
    def get(self, groupid):
        user = self.get_login_user()
        if not user:
            self.redirect("/login?goback=/g/%s" % groupid)
            return
        group = self.get_group(groupid)
        if not group:
            self.render("404.html", info = "Group %s not found." % groupid)
            return
        h = self.request.get("h")
        if h and (generic.hash_str(user.salt + str(group.key)) == h) and not group.user_is_member(user):
            group.add_member(self, user)
        self.redirect("/g/%s" % groupid)
