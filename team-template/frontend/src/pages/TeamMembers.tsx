import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { teamApi } from '../services/api'

interface TeamMember {
  id: string
  email: string
  name: string
  role: 'owner' | 'admin' | 'member' | 'viewer'
  is_active: boolean
  avatar_url?: string
  created_at: string
  last_seen?: string
}

interface Invitation {
  id: string
  email: string
  role: string
  status: 'pending' | 'accepted' | 'cancelled' | 'expired'
  created_at: string
  expires_at: string
}

export default function TeamMembers() {
  const queryClient = useQueryClient()
  const [showInviteModal, setShowInviteModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState<TeamMember | null>(null)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'member' | 'viewer'>('member')
  const [inviteMessage, setInviteMessage] = useState('')
  const [editRole, setEditRole] = useState<'owner' | 'admin' | 'member' | 'viewer'>('member')
  const [showInactive, setShowInactive] = useState(false)
  const [activeTab, setActiveTab] = useState<'members' | 'invitations'>('members')

  const { data: membersData, isLoading: membersLoading } = useQuery({
    queryKey: ['team-members', showInactive],
    queryFn: () => teamApi.listMembers({ include_inactive: showInactive }).then(res => res.data)
  })

  const { data: invitationsData } = useQuery({
    queryKey: ['team-invitations'],
    queryFn: () => teamApi.listInvitations().then(res => res.data)
  })

  const inviteMutation = useMutation({
    mutationFn: (data: { email: string; role: string; message?: string }) =>
      teamApi.createInvitation(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['team-invitations'] })
      setShowInviteModal(false)
      setInviteEmail('')
      setInviteRole('member')
      setInviteMessage('')
    }
  })

  const updateMemberMutation = useMutation({
    mutationFn: ({ memberId, data }: { memberId: string; data: { role?: string; is_active?: boolean } }) =>
      teamApi.updateMember(memberId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['team-members'] })
      setShowEditModal(null)
    }
  })

  const removeMemberMutation = useMutation({
    mutationFn: (memberId: string) => teamApi.removeMember(memberId, true),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['team-members'] })
    }
  })

  const resendInvitationMutation = useMutation({
    mutationFn: (invitationId: string) => teamApi.resendInvitation(invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['team-invitations'] })
    }
  })

  const cancelInvitationMutation = useMutation({
    mutationFn: (invitationId: string) => teamApi.cancelInvitation(invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['team-invitations'] })
    }
  })

  const roleColors: Record<string, string> = {
    owner: 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
    admin: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
    member: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
    viewer: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200'
  }

  const members: TeamMember[] = membersData?.members || []
  const invitations: Invitation[] = invitationsData?.invitations || []
  const pendingInvitations = invitations.filter(i => i.status === 'pending')

  if (membersLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    )
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <Link to="/" className="hover:text-blue-600">Home</Link>
            <span>/</span>
            <span>Team Members</span>
          </div>
          <h1 className="text-2xl font-bold dark:text-white">Team Members</h1>
        </div>
        <button
          onClick={() => setShowInviteModal(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-2"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
          </svg>
          Invite Member
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-sm text-gray-500 dark:text-gray-400">Total Members</h3>
          <p className="text-2xl font-bold dark:text-white">{membersData?.count || 0}</p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-sm text-gray-500 dark:text-gray-400">Admins</h3>
          <p className="text-2xl font-bold text-blue-600">{membersData?.by_role?.admins || 0}</p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-sm text-gray-500 dark:text-gray-400">Members</h3>
          <p className="text-2xl font-bold text-green-600">{membersData?.by_role?.members || 0}</p>
        </div>
        <div className="bg-white dark:bg-gray-800 rounded-lg p-4 shadow">
          <h3 className="text-sm text-gray-500 dark:text-gray-400">Pending Invites</h3>
          <p className="text-2xl font-bold text-orange-600">{pendingInvitations.length}</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-4 mb-4 border-b dark:border-gray-700">
        <button
          onClick={() => setActiveTab('members')}
          className={`pb-2 px-1 border-b-2 transition-colors ${
            activeTab === 'members'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Members ({members.length})
        </button>
        <button
          onClick={() => setActiveTab('invitations')}
          className={`pb-2 px-1 border-b-2 transition-colors ${
            activeTab === 'invitations'
              ? 'border-blue-600 text-blue-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Invitations ({pendingInvitations.length})
        </button>
      </div>

      {activeTab === 'members' && (
        <>
          {/* Filters */}
          <div className="flex items-center gap-4 mb-4">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={showInactive}
                onChange={(e) => setShowInactive(e.target.checked)}
                className="rounded"
              />
              <span className="dark:text-white">Show inactive members</span>
            </label>
          </div>

          {/* Members List */}
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
            <table className="w-full">
              <thead className="bg-gray-50 dark:bg-gray-700">
                <tr>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Member</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Role</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Status</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Joined</th>
                  <th className="text-right px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y dark:divide-gray-700">
                {members.map((member) => (
                  <tr key={member.id} className={!member.is_active ? 'opacity-50' : ''}>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-gray-200 dark:bg-gray-600 flex items-center justify-center text-lg font-medium">
                          {member.name?.charAt(0)?.toUpperCase() || '?'}
                        </div>
                        <div>
                          <div className="font-medium dark:text-white">{member.name}</div>
                          <div className="text-sm text-gray-500">{member.email}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${roleColors[member.role]}`}>
                        {member.role}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                        member.is_active
                          ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200'
                          : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200'
                      }`}>
                        {member.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {new Date(member.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => {
                            setShowEditModal(member)
                            setEditRole(member.role)
                          }}
                          className="p-1 hover:bg-gray-100 dark:hover:bg-gray-700 rounded"
                          title="Edit"
                        >
                          <svg className="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                        </button>
                        {member.role !== 'owner' && (
                          <button
                            onClick={() => {
                              if (confirm(`Remove ${member.name} from the team?`)) {
                                removeMemberMutation.mutate(member.id)
                              }
                            }}
                            className="p-1 hover:bg-red-100 dark:hover:bg-red-900 rounded text-red-600"
                            title="Remove"
                          >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {activeTab === 'invitations' && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow overflow-hidden">
          {pendingInvitations.length === 0 ? (
            <div className="p-8 text-center text-gray-500">
              No pending invitations
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50 dark:bg-gray-700">
                <tr>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Email</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Role</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Sent</th>
                  <th className="text-left px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Expires</th>
                  <th className="text-right px-4 py-3 text-sm font-medium text-gray-500 dark:text-gray-300">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y dark:divide-gray-700">
                {pendingInvitations.map((invitation) => (
                  <tr key={invitation.id}>
                    <td className="px-4 py-3 dark:text-white">{invitation.email}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${roleColors[invitation.role]}`}>
                        {invitation.role}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {new Date(invitation.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-gray-500">
                      {new Date(invitation.expires_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => resendInvitationMutation.mutate(invitation.id)}
                          className="px-3 py-1 text-sm bg-blue-100 text-blue-700 rounded hover:bg-blue-200"
                        >
                          Resend
                        </button>
                        <button
                          onClick={() => cancelInvitationMutation.mutate(invitation.id)}
                          className="px-3 py-1 text-sm bg-red-100 text-red-700 rounded hover:bg-red-200"
                        >
                          Cancel
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Invite Modal */}
      {showInviteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6">
            <h2 className="text-xl font-bold mb-4 dark:text-white">Invite Team Member</h2>
            <form onSubmit={(e) => {
              e.preventDefault()
              inviteMutation.mutate({ email: inviteEmail, role: inviteRole, message: inviteMessage })
            }}>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-1 dark:text-white">Email</label>
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                    placeholder="colleague@example.com"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1 dark:text-white">Role</label>
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value as typeof inviteRole)}
                    className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                  >
                    <option value="admin">Admin - Can manage boards and members</option>
                    <option value="member">Member - Can create and edit cards</option>
                    <option value="viewer">Viewer - Can only view boards</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium mb-1 dark:text-white">Message (optional)</label>
                  <textarea
                    value={inviteMessage}
                    onChange={(e) => setInviteMessage(e.target.value)}
                    className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                    rows={3}
                    placeholder="Add a personal message to the invitation..."
                  />
                </div>
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowInviteModal(false)}
                  className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg dark:text-gray-300 dark:hover:bg-gray-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={inviteMutation.isPending}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {inviteMutation.isPending ? 'Sending...' : 'Send Invitation'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Member Modal */}
      {showEditModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl w-full max-w-md p-6">
            <h2 className="text-xl font-bold mb-4 dark:text-white">Edit Member</h2>
            <div className="flex items-center gap-3 mb-4 pb-4 border-b dark:border-gray-700">
              <div className="w-12 h-12 rounded-full bg-gray-200 dark:bg-gray-600 flex items-center justify-center text-xl font-medium">
                {showEditModal.name?.charAt(0)?.toUpperCase() || '?'}
              </div>
              <div>
                <div className="font-medium dark:text-white">{showEditModal.name}</div>
                <div className="text-sm text-gray-500">{showEditModal.email}</div>
              </div>
            </div>
            <form onSubmit={(e) => {
              e.preventDefault()
              updateMemberMutation.mutate({
                memberId: showEditModal.id,
                data: { role: editRole }
              })
            }}>
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium mb-1 dark:text-white">Role</label>
                  <select
                    value={editRole}
                    onChange={(e) => setEditRole(e.target.value as typeof editRole)}
                    className="w-full px-3 py-2 border rounded-lg dark:bg-gray-700 dark:border-gray-600 dark:text-white"
                    disabled={showEditModal.role === 'owner'}
                  >
                    <option value="owner">Owner - Full control</option>
                    <option value="admin">Admin - Can manage boards and members</option>
                    <option value="member">Member - Can create and edit cards</option>
                    <option value="viewer">Viewer - Can only view boards</option>
                  </select>
                  {showEditModal.role === 'owner' && (
                    <p className="text-sm text-gray-500 mt-1">
                      To change owner role, transfer ownership first.
                    </p>
                  )}
                </div>
                {!showEditModal.is_active && (
                  <div>
                    <button
                      type="button"
                      onClick={() => {
                        updateMemberMutation.mutate({
                          memberId: showEditModal.id,
                          data: { is_active: true }
                        })
                      }}
                      className="w-full px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700"
                    >
                      Reactivate Member
                    </button>
                  </div>
                )}
              </div>
              <div className="flex justify-end gap-3 mt-6">
                <button
                  type="button"
                  onClick={() => setShowEditModal(null)}
                  className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg dark:text-gray-300 dark:hover:bg-gray-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={updateMemberMutation.isPending || showEditModal.role === 'owner'}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {updateMemberMutation.isPending ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
