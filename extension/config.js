// The ONLY place with LinkedIn-specific selectors, warning phrases and pacing.
// When LinkedIn changes its pages, fix the selectors here. Used by the background worker and the page readers.
self.LJT_CONFIG = {
  SERVER: "http://127.0.0.1:5000",               // default dashboard (local)
  // Dashboards allowed to start runs (the one that presses Start is used). Hosted: any *.onrender.com app.
  // Using another host? Add it here AND to host_permissions + content_scripts.matches in manifest.json.
  DASHBOARDS: [/^http:\/\/(127\.0\.0\.1|localhost):5000$/, /^https:\/\/[a-z0-9-]+\.onrender\.com$/],
  TAB_GROUP_TITLE: "JobHarvest",
  MAX_PARALLEL_TABS: 8,                          // upper limit when a run has many jobs to read
  PARALLEL_TABS: 3,                              // LinkedIn tabs reading jobs at the same time (1 = one at a time)

  PACING: {
    minPauseMs: 3000, maxPauseMs: 5000,          // before every LinkedIn PAGE LOAD (results page, company page)
    cardMinMs: 900, cardMaxMs: 1800,             // before clicking each job card (no page load, panel only)
    parallelMinMs: 600, parallelMaxMs: 1200,      // each extra tab, before opening its next job
    jobMs: 8000, readBudgetMs: 25000,            // time budget: windows = jobs needed x jobMs / readBudgetMs
    settleMs: 600,                               // after the panel shows the job, before reading it
    breakEveryPages: 25, breakMinMs: 8000, breakMaxMs: 12000, // extra rest
    pageLoadTimeoutMs: 60000,                    // a page that never loads ends that step
    renderWaitMs: 20000,                         // how long to wait for content to appear
    companyWaitMs: 8000,                         // a company page that has not shown its details by then is skipped
  },

  // Stop immediately (and keep the tab open) when any of these appear.
  STOP_URL_PARTS: ["/checkpoint/", "/authwall", "/login", "/uas/", "/challenge", "/signup", "/m/login"],
  STOP_TEXT: [
    /unusual activity/i, /security (check|verification)/i, /let's do a quick security check/i,
    /verify (that )?you('| a)re (a )?human/i, /captcha/i, /too many requests/i,
    /you('|’)ve reached the (weekly|monthly|commercial use)? ?limit/i, /temporarily (restricted|limited)/i,
    /your account has been restricted/i,
  ],

  SEL: {
    signedInMarkers: ["#global-nav", ".global-nav", "header.global-nav__content", "[data-test-global-nav]"],
    // job search results
    // new layout (verified 2026-11-11 on a real page) first, then the classic layout
    searchCards: ["div[role=button][componentkey^='job-card-component-ref-']", "li[data-occludable-job-id]", "[data-job-id]"],
    searchCardTitle: [".job-card-list__title--link", ".job-card-list__title", ".job-card-container__link strong", "a.job-card-container__link"],
    searchCardCompany: [".artdeco-entity-lockup__subtitle", ".job-card-container__primary-description", ".job-card-container__company-name"],
    searchCardCompanyLink: ["a[href*='/company/']"],
    searchCardLocation: [".job-card-container__metadata-wrapper li", ".artdeco-entity-lockup__caption", ".job-card-container__metadata-item"],
    searchList: [".jobs-search-results-list", ".scaffold-layout__list > div", ".scaffold-layout__list",
      "[data-results-list-top-scroll-sentinel] + ul", "div[aria-label*='search results' i]"],
    detailPane: [".jobs-search__job-details", ".jobs-details", ".scaffold-layout__detail"],
    searchNoResults: [".jobs-search-no-results-banner", ".jobs-search-two-pane__no-results-banner--expand"],
    searchNextButton: ["button.jobs-search-pagination__button--next", "button[aria-label='View next page']",
      "li.artdeco-pagination__indicator--number.active + li"],
    // clicking a card on the results list and reading the detail panel on the right
    cardClickTarget: ["a.job-card-container__link", "a.job-card-list__title--link", ".job-card-container--clickable", ".job-card-container"],
    paneTitle: [".job-details-jobs-unified-top-card__job-title", ".jobs-unified-top-card__job-title", ".jobs-details__main-content h1", ".jobs-search__job-details h1"],
    paneJobLink: [".job-details-jobs-unified-top-card__job-title a[href*='/jobs/view/']", ".jobs-details a[href*='/jobs/view/']"],
    descriptionMoreButton: [".jobs-description__footer-button", "button.jobs-description__footer-button", ".jobs-description button[aria-label*='more' i]",
      "#job-details + button", ".feed-shared-inline-show-more-text__see-more-less-toggle"],
    // job page (fields are read by extract.js)
    jobReady: [".job-details-jobs-unified-top-card__job-title", ".jobs-unified-top-card__job-title", "#job-details", ".jobs-description__content", ".top-card-layout__title"],
    // company About page
    companyReady: ["dl dt", "[data-test-id^='about-us__']", ".org-page-details__definition-term"],
    pageNotFound: [/this page doesn('|’)t exist/i, /page not found/i],
  },
};
