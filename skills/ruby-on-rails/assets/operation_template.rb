# app/domains/<domain>/operations/<verb_noun>.rb
# Convention: VerbNoun, one public `.call`, keyword arguments, returns ApplicationResult.
# Expected failures → ApplicationResult.failure; unexpected problems raise.
#
# Kernel prerequisite (app/models/application_result.rb):
#   ApplicationResult = Data.define(:value, :errors) do
#     def self.success(value = nil) = new(value:, errors: [])
#     def self.failure(*errors) = new(value: nil, errors: errors.flatten)
#     def success? = errors.empty?
#     def failure? = !success?
#   end
module Billing
  class CancelSubscription
    def self.call(...) = new(...).call

    def initialize(subscription:, cancelled_by:, at: Time.current)
      @subscription = subscription
      @cancelled_by = cancelled_by
      @at = at
    end

    def call
      return ApplicationResult.failure("Subscription is already cancelled") if @subscription.cancelled?

      @subscription.transaction { cancel && notify }
      ApplicationResult.success(@subscription)
    end

    private
      def cancel = @subscription.update!(status: :cancelled, cancelled_at: @at, cancelled_by: @cancelled_by)

      # Cross-domain side effect through the other domain's public API, enqueued after commit.
      def notify = Communications::Notify.later(user: @cancelled_by, template: :subscription_cancelled,
                                                subscription_id: @subscription.id)
  end
end

# spec/domains/billing/operations/cancel_subscription_spec.rb
# RSpec.describe Billing::CancelSubscription do
#   subject(:result) { described_class.call(subscription:, cancelled_by: user) }
#   let(:user) { create(:user) }
#   let(:subscription) { create(:billing_subscription, :active) }
#
#   it "cancels and notifies" do
#     expect(result).to be_success
#     expect(subscription.reload).to be_cancelled
#     expect(Communications::NotifyJob).to have_been_enqueued
#   end
# end
