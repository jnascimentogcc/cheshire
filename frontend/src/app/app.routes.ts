import { Routes } from '@angular/router';

import { requireArchitect, requireLogin } from './core/auth';

export const routes: Routes = [
  {
    path: 'login',
    title: 'Sign in · Cheshire',
    loadComponent: () => import('./pages/login').then((m) => m.LoginPage),
  },
  {
    path: 'accept-invitation',
    title: 'Accept invitation · Cheshire',
    loadComponent: () => import('./pages/accept-invitation').then((m) => m.AcceptInvitationPage),
  },
  {
    path: 'consult',
    canActivate: [requireLogin],
    children: [
      {
        path: '',
        title: 'Consultations · Cheshire',
        loadComponent: () => import('./consult/list').then((m) => m.ConsultListPage),
      },
      {
        path: 'new',
        title: 'New consultation · Cheshire',
        loadComponent: () => import('./consult/new').then((m) => m.ConsultNewPage),
      },
      {
        path: ':id',
        title: 'Consultation · Cheshire',
        loadComponent: () => import('./consult/session/page').then((m) => m.SessionPage),
      },
    ],
  },
  {
    path: 'catalog',
    canActivate: [requireLogin],
    children: [
      {
        path: '',
        title: 'Catalog · Cheshire',
        loadComponent: () => import('./catalog/home').then((m) => m.CatalogHomePage),
      },
      {
        path: 'vocabulary',
        title: 'Vocabulary · Cheshire',
        loadComponent: () => import('./catalog/list').then((m) => m.CatalogVocabularyPage),
      },
      {
        path: 'reference-cases',
        canActivate: [requireArchitect],
        title: 'Reference cases · Cheshire',
        loadComponent: () => import('./catalog/tools').then((m) => m.ReferenceCasesPage),
      },
      {
        path: 'import-export',
        canActivate: [requireArchitect],
        title: 'Import and export · Cheshire',
        loadComponent: () => import('./catalog/tools').then((m) => m.ImportExportPage),
      },
      {
        path: 'interview',
        canActivate: [requireArchitect],
        title: 'Interview · Cheshire',
        loadComponent: () => import('./catalog/interview').then((m) => m.InterviewStartPage),
      },
      {
        path: 'interview/:id',
        canActivate: [requireArchitect],
        title: 'Interview · Cheshire',
        loadComponent: () => import('./catalog/interview').then((m) => m.InterviewPage),
      },
      {
        path: ':kinds',
        title: 'Catalog · Cheshire',
        loadComponent: () => import('./catalog/list').then((m) => m.CatalogListPage),
      },
      {
        path: ':kinds/new',
        canActivate: [requireArchitect],
        title: 'New item · Cheshire',
        loadComponent: () => import('./catalog/edit').then((m) => m.CatalogEditPage),
      },
      {
        path: ':kinds/:slug',
        title: 'Catalog item · Cheshire',
        loadComponent: () => import('./catalog/item').then((m) => m.CatalogItemPage),
      },
      {
        path: ':kinds/:slug/edit',
        canActivate: [requireArchitect],
        title: 'Edit item · Cheshire',
        loadComponent: () => import('./catalog/edit').then((m) => m.CatalogEditPage),
      },
    ],
  },
  {
    path: 'discussions',
    canActivate: [requireLogin, requireArchitect],
    children: [
      {
        path: '',
        title: 'Discussions · Cheshire',
        loadComponent: () => import('./discussions/inbox').then((m) => m.DiscussionInboxPage),
      },
      {
        path: 'new',
        title: 'New discussion · Cheshire',
        loadComponent: () => import('./discussions/new').then((m) => m.DiscussionNewPage),
      },
      {
        path: ':id',
        title: 'Discussion · Cheshire',
        loadComponent: () => import('./discussions/page').then((m) => m.DiscussionPage),
      },
    ],
  },
  {
    path: 'notifications',
    canActivate: [requireLogin, requireArchitect],
    title: 'Notifications · Cheshire',
    loadComponent: () => import('./discussions/notifications').then((m) => m.NotificationsPage),
  },
  { path: '', pathMatch: 'full', redirectTo: 'consult' },
  {
    path: '**',
    title: 'Not found · Cheshire',
    loadComponent: () => import('./pages/not-found').then((m) => m.NotFoundPage),
  },
];
