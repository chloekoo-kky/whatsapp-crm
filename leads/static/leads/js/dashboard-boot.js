(function () {
  if (window.__leadsDashboardSkip) return;
      if (window.__leadsDashboardBooted) {
        window.__leadsDashboardSkip = true;
        return;
      }
      window.__leadsDashboardBooted = true;
      window.__leadsDashboardSkip = false;
      window.cfgEl = document.getElementById('dashboard-js-config');
      window.dashboardJsConfig = JSON.parse((cfgEl && cfgEl.textContent) || '{}');
      dashboardJsConfig.getLeadsTableUrl = dashboardJsConfig.getLeadsTableUrl || "/leads/ajax/leads-table/";
      dashboardJsConfig.getLeadChatIndicatorsUrl = dashboardJsConfig.getLeadChatIndicatorsUrl || "/leads/ajax/chat-indicators/";
      dashboardJsConfig.createLeadGroupUrl = dashboardJsConfig.createLeadGroupUrl || "/leads/api/lead-groups/";
      dashboardJsConfig.bulkAssignGroupUrl = dashboardJsConfig.bulkAssignGroupUrl || "/leads/api/assign-group/";
      dashboardJsConfig.reorderLeadGroupsUrl = dashboardJsConfig.reorderLeadGroupsUrl || "/leads/api/lead-groups/reorder/";
      dashboardJsConfig.reorderLeadsUrl = dashboardJsConfig.reorderLeadsUrl || "/leads/api/leads/reorder/";
      dashboardJsConfig.exportXlsxUrl = dashboardJsConfig.exportXlsxUrl || "/leads/export/xlsx/";
      dashboardJsConfig.exportFullBackupUrl = dashboardJsConfig.exportFullBackupUrl || "/leads/export/backup/";
      dashboardJsConfig.importFullBackupUrl = dashboardJsConfig.importFullBackupUrl || "/leads/import/backup/";
      dashboardJsConfig.bulkManualUrl = dashboardJsConfig.bulkManualUrl || "/leads/api/bulk-manual/";
      dashboardJsConfig.bulkWhatsappQueueUrl = dashboardJsConfig.bulkWhatsappQueueUrl || "/leads/api/bulk-whatsapp-queue/";
      dashboardJsConfig.bulkDequeueUrl = dashboardJsConfig.bulkDequeueUrl || "/leads/api/bulk-dequeue/";
      dashboardJsConfig.bulkAssignBatchUrl = dashboardJsConfig.bulkAssignBatchUrl || "/leads/api/bulk-assign-batch/";
      dashboardJsConfig.whatsappBatchesJsonUrl = dashboardJsConfig.whatsappBatchesJsonUrl || "/leads/ajax/whatsapp/batches/";
      dashboardJsConfig.leadManualCreateUrl = dashboardJsConfig.leadManualCreateUrl || "/leads/api/leads/manual/";
      dashboardJsConfig.huntApiPath = dashboardJsConfig.huntApiPath || "";
      dashboardJsConfig.initialLeadGroupTabIdFromPage = dashboardJsConfig.initialLeadGroupTabIdFromPage || "";
      dashboardJsConfig.queueGroupTabId = dashboardJsConfig.queueGroupTabId || "";
      dashboardJsConfig.trashGroupTabId = dashboardJsConfig.trashGroupTabId || "";
      dashboardJsConfig.defaultLimit = dashboardJsConfig.defaultLimit || 100;
      window.activeSearchRecordId = dashboardJsConfig.activeSearchRecordId != null ? dashboardJsConfig.activeSearchRecordId : null;
      /* Hardcoded URLs: avoids view-context + Gunicorn stale imports; matches leads/urls and Ninja mount. */
      window.clinicApiDetailPrefix = "/api/clinics/";
      window.clinicUpdateUrlTemplate = "/leads/api/clinic/__ID__/";
      window.leadDeleteUrlTemplate = "/leads/api/clinic/__ID__/delete/";
      window.leadVipUrlTemplate = "/leads/api/clinic/__ID__/very-important/";
      window.leadConversationLogUrlTemplate = "/leads/api/clinic/__ID__/conversation-log/";
      window.REQUIRE_WEBSITE_KEY = "clinic_crm_require_website";
      window.LEADS_PER_PAGE_KEY = "clinic_crm_leads_per_page";
      window.CHAT_INDICATOR_POLL_KEY = "clinic_crm_chat_indicator_poll";
      window.CHAT_INDICATOR_POLL_MS = 15000;
      window.VIEW_MODE_KEY = "clinic_crm_clinic_view";
      window.LEAD_SORT_KEY = "clinic_crm_lead_sort";
      window.shopTypesApiPath = "/leads/api/shop-types/";
      window.shopTypeDeleteUrlTemplate = "/leads/api/shop-types/__ID__/";
})();
