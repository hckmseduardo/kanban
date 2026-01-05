import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { workspacesApi, appTemplatesApi, AppTemplate } from '../services/api'

export default function CreateWorkspacePage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null)
  const [error, setError] = useState('')

  const { data: templates } = useQuery({
    queryKey: ['app-templates'],
    queryFn: () => appTemplatesApi.list().then(res => res.data.templates),
    staleTime: 10 * 60 * 1000,
  })

  const createWorkspace = useMutation({
    mutationFn: (data: { name: string; slug: string; description?: string; app_template_slug?: string }) =>
      workspacesApi.create(data),
    onSuccess: () => {
      // Invalidate the workspaces cache so the list refreshes
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      navigate('/')
    },
    onError: (err: any) => {
      setError(err.response?.data?.detail || 'Failed to create workspace')
    }
  })

  const handleNameChange = (value: string) => {
    setName(value)
    const generatedSlug = value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '')
    setSlug(generatedSlug)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!name.trim()) {
      setError('Workspace name is required')
      return
    }

    if (!slug.trim() || slug.length < 3) {
      setError('Workspace slug must be at least 3 characters')
      return
    }

    createWorkspace.mutate({
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim() || undefined,
      app_template_slug: selectedTemplate || undefined
    })
  }

  return (
    <div className="max-w-3xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-6">Create New Workspace</h1>

      <form onSubmit={handleSubmit} className="bg-white dark:bg-dark-800 shadow dark:shadow-dark-700/30 rounded-xl p-6 space-y-6">
        {error && (
          <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg">
            {error}
          </div>
        )}

        <div>
          <label htmlFor="name" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            Workspace Name *
          </label>
          <input
            type="text"
            id="name"
            value={name}
            onChange={(e) => handleNameChange(e.target.value)}
            className="mt-1 block w-full rounded-lg border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            placeholder="My Project"
          />
        </div>

        <div>
          <label htmlFor="slug" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            Workspace URL Slug *
          </label>
          <div className="mt-1 flex rounded-lg shadow-sm">
            <span className="inline-flex items-center px-3 rounded-l-lg border border-r-0 border-gray-300 dark:border-dark-600 bg-gray-50 dark:bg-dark-700 text-gray-500 dark:text-gray-400 sm:text-sm">
              https://
            </span>
            <input
              type="text"
              id="slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ''))}
              className="flex-1 min-w-0 block w-full px-3 py-2 rounded-none border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
              placeholder="my-project"
            />
            <span className="inline-flex items-center px-3 rounded-r-lg border border-l-0 border-gray-300 dark:border-dark-600 bg-gray-50 dark:bg-dark-700 text-gray-500 dark:text-gray-400 sm:text-sm">
              .kanban.amazing-ai.tools
            </span>
          </div>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
            3-63 characters, lowercase letters, numbers, and hyphens only
          </p>
        </div>

        <div>
          <label htmlFor="description" className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            Description
          </label>
          <textarea
            id="description"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="mt-1 block w-full rounded-lg border-gray-300 dark:border-dark-600 bg-white dark:bg-dark-700 text-gray-900 dark:text-gray-100 shadow-sm focus:border-primary-500 focus:ring-primary-500 sm:text-sm"
            placeholder="A brief description of your workspace..."
          />
        </div>

        {/* App Template Selection */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
            Workspace Type
          </label>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Kanban Only Option */}
            <button
              type="button"
              onClick={() => setSelectedTemplate(null)}
              className={`relative rounded-xl border-2 p-4 flex flex-col transition-all ${
                selectedTemplate === null
                  ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                  : 'border-gray-200 dark:border-dark-600 hover:border-gray-300 dark:hover:border-dark-500'
              }`}
            >
              <div className="flex items-center gap-3">
                <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${
                  selectedTemplate === null
                    ? 'bg-primary-500 text-white'
                    : 'bg-gray-100 dark:bg-dark-700 text-gray-500 dark:text-gray-400'
                }`}>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                </div>
                <div className="text-left">
                  <h3 className={`font-semibold ${
                    selectedTemplate === null ? 'text-primary-700 dark:text-primary-300' : 'text-gray-900 dark:text-gray-100'
                  }`}>
                    Kanban Only
                  </h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Just boards and tasks
                  </p>
                </div>
              </div>
              {selectedTemplate === null && (
                <div className="absolute top-2 right-2">
                  <svg className="w-5 h-5 text-primary-500" fill="currentColor" viewBox="0 0 20 20">
                    <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                  </svg>
                </div>
              )}
            </button>

            {/* App Templates */}
            {(templates || []).filter(t => t.active).map((template) => (
              <button
                key={template.slug}
                type="button"
                onClick={() => setSelectedTemplate(template.slug)}
                className={`relative rounded-xl border-2 p-4 flex flex-col transition-all ${
                  selectedTemplate === template.slug
                    ? 'border-primary-500 bg-primary-50 dark:bg-primary-900/20'
                    : 'border-gray-200 dark:border-dark-600 hover:border-gray-300 dark:hover:border-dark-500'
                }`}
              >
                <div className="flex items-center gap-3">
                  <div className={`h-10 w-10 rounded-lg flex items-center justify-center ${
                    selectedTemplate === template.slug
                      ? 'bg-primary-500 text-white'
                      : 'bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400'
                  }`}>
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
                    </svg>
                  </div>
                  <div className="text-left">
                    <h3 className={`font-semibold ${
                      selectedTemplate === template.slug ? 'text-primary-700 dark:text-primary-300' : 'text-gray-900 dark:text-gray-100'
                    }`}>
                      {template.name}
                    </h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      {template.description}
                    </p>
                  </div>
                </div>
                {selectedTemplate === template.slug && (
                  <div className="absolute top-2 right-2">
                    <svg className="w-5 h-5 text-primary-500" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                    </svg>
                  </div>
                )}
              </button>
            ))}
          </div>
        </div>

        <div className="flex justify-end space-x-4 pt-4">
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="px-4 py-2 text-sm font-medium text-gray-700 dark:text-gray-300 hover:text-gray-500 dark:hover:text-gray-100"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={createWorkspace.isPending}
            className="inline-flex items-center px-4 py-2 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50"
          >
            {createWorkspace.isPending ? (
              <>
                <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                Creating...
              </>
            ) : (
              'Create Workspace'
            )}
          </button>
        </div>
      </form>

      {/* Info Box */}
      <div className="mt-6 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl p-4">
        <h3 className="text-sm font-medium text-blue-800 dark:text-blue-300">What happens next?</h3>
        <ul className="mt-2 text-sm text-blue-700 dark:text-blue-400 list-disc list-inside space-y-1">
          <li>A kanban team will be provisioned at {slug || 'your-slug'}.kanban.amazing-ai.tools</li>
          {selectedTemplate && (
            <>
              <li>A full-stack app will be deployed at {slug || 'your-slug'}.app.amazing-ai.tools</li>
              <li>A GitHub repository will be created from the {selectedTemplate} template</li>
              <li>You'll be able to create sandboxes for feature development</li>
            </>
          )}
          <li>SSL certificates will be issued automatically</li>
        </ul>
      </div>
    </div>
  )
}
