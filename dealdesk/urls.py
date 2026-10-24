from django.contrib.auth import views as auth_views
from django.urls import include, path

from checklists import views as checklists
from commissions import views as commissions
from core import views as core
from crm import views as crm
from deadlines import views as deadlines
from deals import views as deals
from imports import views as imports
from properties import views as properties
from reports import views as reports

urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", core.hero, name="hero"),
    path("dashboard/", core.dashboard, name="dashboard"),
    path("brand/photo/", core.brand_photo, name="brand_photo"),
    path("search/", core.search, name="search"),
    path("search/quick/", core.quick_search, name="quick_search"),
    path("notifications/", core.notifications, name="notifications"),
    path("notifications/<int:pk>/read/", core.notification_read, name="notification_read"),
    path("views/save/", core.save_view, name="save_view"),

    # Settings
    path("settings/", core.settings_index, name="settings_index"),
    path("settings/users/", core.user_list, name="user_list"),
    path("settings/users/new/", core.user_create, name="user_create"),
    path("settings/users/<int:pk>/", core.user_edit, name="user_edit"),
    path("settings/stages/", core.stage_list, name="stage_list"),
    path("settings/stages/new/", core.stage_edit, name="stage_create"),
    path("settings/stages/<int:pk>/", core.stage_edit, name="stage_edit"),
    path("settings/holidays/", core.holiday_list, name="holiday_list"),
    path("settings/holidays/<int:pk>/add/", core.holiday_add, name="holiday_add"),
    path("settings/reminders/", core.reminder_settings, name="reminder_settings"),
    path("settings/reminders/log/", core.reminder_log, name="reminder_log"),
    path("settings/audit/", core.audit_log, name="audit_log"),
    path("settings/archived/", core.archived, name="archived"),
    path("settings/archived/<str:kind>/<int:pk>/restore/", core.restore, name="restore"),
    path("settings/requirements/", core.requirements, name="requirements"),
    path("settings/jobs/", core.jobs, name="jobs"),
    path("settings/templates/", checklists.template_list, name="template_list"),
    path("settings/templates/<int:tpl_pk>/items/new/", checklists.template_item, name="template_item_create"),
    path("settings/templates/<int:tpl_pk>/items/<int:pk>/", checklists.template_item, name="template_item_edit"),

    # Properties
    path("properties/", properties.property_list, name="property_list"),
    path("properties/new/", properties.property_form, name="property_create"),
    path("properties/<int:pk>/", properties.property_detail, name="property_detail"),
    path("properties/<int:pk>/edit/", properties.property_form, name="property_edit"),
    path("properties/<int:pk>/archive/", properties.property_archive, name="property_archive"),
    path("properties/<int:pk>/<str:kind>/new/", properties.property_subrecord, name="property_sub"),
    path("properties/<int:pk>/<str:kind>/<int:item>/", properties.property_subrecord, name="property_sub_edit"),

    # Deals
    path("deals/", deals.deal_list, name="deal_list"),
    path("deals/deposits/", deals.deposit_list, name="deposit_list"),
    path("deals/new/", deals.deal_create, name="deal_create"),
    path("deals/<int:pk>/", deals.deal_detail, name="deal_detail"),
    path("deals/<int:pk>/edit/", deals.deal_edit, name="deal_edit"),
    path("deals/<int:pk>/stage/", deals.deal_stage, name="deal_stage"),
    path("deals/<int:pk>/close/", deals.deal_close, name="deal_close"),
    path("deals/<int:pk>/status/", deals.deal_status, name="deal_status"),
    path("deals/<int:pk>/archive/", deals.deal_archive, name="deal_archive"),
    path("deals/<int:pk>/event/", deals.deal_event, name="deal_event"),
    path("deals/<int:pk>/term/", deals.deal_term, name="deal_term"),
    path("deals/<int:pk>/key-dates/", deals.deal_key_dates, name="deal_key_dates"),
    path("deals/<int:pk>/extend/", deals.deal_extend, name="deal_extend"),
    path("deals/<int:pk>/commission/", deals.deal_commission, name="deal_commission"),
    path("deals/<int:pk>/commission/receipt/", deals.deal_receipt, name="deal_receipt"),
    path("deals/<int:pk>/commission/receipt/<int:entry>/reverse/", deals.deal_receipt_reverse, name="deal_receipt_reverse"),
    path("deals/<int:pk>/deadlines/generate/", deals.deal_generate_deadlines, name="deal_generate_deadlines"),
    path("deals/<int:pk>/checklist/apply/", deals.deal_apply_checklist, name="deal_apply_checklist"),
    path("deals/<int:deal_pk>/checklist/new/", checklists.item_form, name="checklist_item_create"),
    path("deals/<int:pk>/draft/", deals.deal_draft, name="deal_draft"),
    path("deals/<int:pk>/calendar.ics", deadlines.deal_ics, name="deal_ics"),
    path("deals/<int:pk>/<str:kind>/new/", deals.deal_subrecord, name="deal_sub"),
    path("deals/<int:pk>/<str:kind>/<int:item>/", deals.deal_subrecord, name="deal_sub_edit"),
    path("drafts/<int:pk>/", deals.draft_edit, name="draft_edit"),
    path("issues/", deals.issue_list, name="issue_list"),
    path("issues/new/", deals.issue_form, name="issue_create"),
    path("issues/<int:pk>/", deals.issue_detail, name="issue_detail"),
    path("issues/<int:pk>/edit/", deals.issue_form, name="issue_edit"),
    path("issues/<int:pk>/statement/", deals.issue_statement, name="issue_statement"),

    # Deadlines
    path("deadlines/", deadlines.deadline_list, name="deadline_list"),
    path("deadlines/new/", deadlines.deadline_form, name="deadline_create"),
    path("deadlines/export.ics", deadlines.deadline_ics, name="deadline_ics"),
    path("deadlines/<int:pk>/", deadlines.deadline_detail, name="deadline_detail"),
    path("deadlines/<int:pk>/edit/", deadlines.deadline_form, name="deadline_edit"),
    path("deadlines/<int:pk>/state/", deadlines.deadline_state, name="deadline_state"),
    path("deadlines/<int:pk>/recompute/", deadlines.deadline_recompute, name="deadline_recompute"),
    path("calendar/feed/<str:token>.ics", deadlines.calendar_feed, name="calendar_feed"),

    # Tasks & checklists
    path("tasks/", checklists.checklist_list, name="checklist_list"),
    path("tasks/<int:pk>/", checklists.item_form, name="checklist_item_edit"),

    # Contacts
    path("contacts/", crm.contact_list, name="contact_list"),
    path("contacts/new/", crm.contact_form, name="contact_create"),
    path("contacts/<int:pk>/", crm.contact_detail, name="contact_detail"),
    path("contacts/<int:pk>/edit/", crm.contact_form, name="contact_edit"),
    path("companies/new/", crm.organization_form, name="organization_create"),
    path("companies/<int:pk>/", crm.organization_detail, name="organization_detail"),
    path("companies/<int:pk>/edit/", crm.organization_form, name="organization_edit"),
    path("contacts/archive/<str:kind>/<int:pk>/", crm.archive_party, name="archive_party"),

    # Commissions
    path("commissions/", commissions.commission_list, name="commission_list"),
    path("commissions/ledger/", commissions.ledger_list, name="ledger_list"),
    path("commissions/new/", commissions.agreement_form, name="commission_create"),
    path("commissions/<int:pk>/", commissions.agreement_detail, name="commission_detail"),
    path("commissions/<int:pk>/edit/", commissions.agreement_form, name="commission_edit"),
    path("commissions/<int:pk>/archive/", commissions.agreement_archive, name="commission_archive"),
    path("commissions/<int:pk>/entry/", commissions.entry_create, name="ledger_entry_create"),
    path("commissions/entries/<int:pk>/reverse/", commissions.entry_reverse, name="ledger_entry_reverse"),
    path("commissions/<int:pk>/<str:kind>/new/", commissions.agreement_sub, name="commission_sub"),
    path("commissions/<int:pk>/<str:kind>/<int:item>/", commissions.agreement_sub, name="commission_sub_edit"),

    # Reports
    path("reports/", reports.report_index, name="report_index"),
    path("reports/<str:metric>/", reports.report_detail, name="report_detail"),

    # Imports
    path("imports/", imports.import_list, name="import_list"),
    path("imports/template/<str:kind>.csv", imports.import_template, name="import_template"),
    path("imports/<int:pk>/", imports.import_detail, name="import_detail"),
    path("imports/<int:pk>/commit/", imports.import_commit, name="import_commit"),
    path("imports/<int:pk>/revert/", imports.import_revert, name="import_revert"),
    path("imports/<int:pk>/report.csv", imports.import_errors, name="import_errors"),
    path("imports/<int:pk>/rows/<int:row_pk>/", imports.import_row_action, name="import_row_action"),
]
